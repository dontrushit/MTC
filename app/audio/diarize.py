"""Split a mixed mono phone recording into two speaker tracks.

The first person to speak becomes the manager. Pass --swap later if that is wrong.
Speaker identity comes from a local voice encoder (no download, no account).
"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf

from app.audio.vad import speech_segments
from app.db.models import SpeakerRole

SAMPLE_RATE = 16000
MIN_EMBED_SEC = 0.45
WINDOW_SEC = 1.2
HOP_SEC = 0.4
# Weaker than this, two fragments are not evidence of the same voice.
ABSORB_SIM = 0.6
SAME_SPEAKER_SIMILARITY = 0.72


def load_mono_16k(path: Path | str) -> np.ndarray:
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(path),
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-f",
        "f32le",
        "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True, check=True)
    return np.frombuffer(result.stdout, dtype=np.float32).copy()


@lru_cache(maxsize=1)
def _encoder():
    from resemblyzer import VoiceEncoder

    return VoiceEncoder(device="cpu", verbose=False)


def _embed(wav: np.ndarray) -> np.ndarray | None:
    if len(wav) < int(MIN_EMBED_SEC * SAMPLE_RATE):
        return None
    peak = float(np.max(np.abs(wav)))
    if peak < 1e-4:
        return None
    normed = (wav / peak * 0.95).astype(np.float32, copy=False)
    vector = np.asarray(_encoder().embed_utterance(normed), dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if norm < 1e-6:
        return None
    return vector / norm


def _group_similarity(sim: np.ndarray, left: list[int], right: list[int]) -> float:
    scores = [sim[i, j] for i in left for j in right]
    return float(np.mean(scores)) if scores else 0.0


def _cluster_few(vectors: np.ndarray) -> np.ndarray:
    """Two voices when there are only a handful of fragments."""
    similarity = vectors @ vectors.T
    count = len(vectors)
    labels = np.zeros(count, dtype=int)
    groups: list[list[int]] = [[0]]
    for index in range(1, count):
        scores = [
            float(np.mean([similarity[index, other] for other in group])) for group in groups
        ]
        best = int(np.argmax(scores))
        if scores[best] >= SAME_SPEAKER_SIMILARITY or len(groups) >= 2:
            groups[best].append(index)
        else:
            groups.append([index])
    if len(groups) < 2:
        return labels
    if _group_similarity(similarity, groups[0], groups[1]) > SAME_SPEAKER_SIMILARITY:
        return labels
    for index in groups[1]:
        labels[index] = 1
    return labels


def cluster_two(vectors: np.ndarray) -> np.ndarray:
    """Two speakers from L2-normalized embeddings.

    A long recording is split by the main cut of the similarity graph. Comparing fragments
    one by one would chain both voices together, because neighboring windows overlap.
    """
    count = len(vectors)
    labels = np.zeros(count, dtype=int)
    if count < 2:
        return labels
    if count < 12:
        return _cluster_few(vectors)

    similarity = vectors @ vectors.T
    affinity = similarity.copy()
    np.fill_diagonal(affinity, 0.0)
    affinity[affinity < ABSORB_SIM] = 0.0
    degree = affinity.sum(axis=1)
    degree[degree == 0] = 1.0
    scale = 1.0 / np.sqrt(degree)
    laplacian = np.eye(count) - scale[:, None] * affinity * scale[None, :]
    _, eigenvectors = np.linalg.eigh(laplacian)
    split = eigenvectors[:, 1]
    if float(split.max() - split.min()) < 1e-3:
        return labels

    labels = (split >= float(np.median(split))).astype(int)
    if labels.min() == labels.max():
        return np.zeros(count, dtype=int)
    sides = [np.flatnonzero(labels == speaker).tolist() for speaker in (0, 1)]
    if _group_similarity(similarity, sides[0], sides[1]) > SAME_SPEAKER_SIMILARITY:
        return np.zeros(count, dtype=int)
    return labels


def speech_windows(segments: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Slice long turns into overlapping windows so a speaker change inside is visible."""
    windows: list[tuple[float, float]] = []
    for start, end in segments:
        if end - start <= WINDOW_SEC + 0.2:
            windows.append((start, end))
            continue
        position = start
        covered = start
        while position + WINDOW_SEC <= end + 1e-6:
            windows.append((position, position + WINDOW_SEC))
            covered = position + WINDOW_SEC
            position += HOP_SEC
        if end - covered > 0.3:
            windows.append((max(start, end - WINDOW_SEC), end))
    return windows


def label_segments(
    segments: list[tuple[float, float]],
    embeddings: list[np.ndarray | None],
) -> list[int]:
    """Label each segment 0 or 1. Speaker 0 is whoever starts the call."""
    usable = [(index, vector) for index, vector in enumerate(embeddings) if vector is not None]
    if len(usable) < 2:
        return [0] * len(segments)

    vectors = np.stack([vector for _, vector in usable])
    raw = cluster_two(vectors)
    if raw.min() == raw.max():
        return [0] * len(segments)

    labels: list[int | None] = [None] * len(segments)
    for (index, _), cluster in zip(usable, raw, strict=True):
        labels[index] = int(cluster)

    for index in range(len(labels)):
        if labels[index] is not None:
            continue
        nearest = min(
            (i for i in range(len(labels)) if labels[i] is not None),
            key=lambda i: abs(segments[i][0] - segments[index][0]),
        )
        labels[index] = labels[nearest]

    _smooth_short_flips(segments, labels)
    if labels[0] == 1:
        labels = [1 - int(label) for label in labels]
    return [int(label) for label in labels]


def _smooth_short_flips(
    segments: list[tuple[float, float]],
    labels: list[int | None],
) -> None:
    """Relabel a short turn sandwiched between the other speaker."""
    for index in range(1, len(labels) - 1):
        duration = segments[index][1] - segments[index][0]
        if duration >= MIN_EMBED_SEC:
            continue
        left, right = labels[index - 1], labels[index + 1]
        if left is not None and left == right and labels[index] != left:
            labels[index] = left


def merge_labeled(
    segments: list[tuple[float, float]],
    labels: list[int],
    gap_sec: float = 0.3,
) -> list[tuple[float, float, int]]:
    if not segments:
        return []
    merged: list[tuple[float, float, int]] = [
        (segments[0][0], segments[0][1], labels[0])
    ]
    for (start, end), label in zip(segments[1:], labels[1:], strict=True):
        prev_start, prev_end, prev_label = merged[-1]
        if label == prev_label and start - prev_end < gap_sec:
            merged[-1] = (prev_start, max(prev_end, end), prev_label)
        else:
            merged.append((start, end, label))
    return merged


def _speaker_frames(
    windows: list[tuple[float, float]],
    labels: list[int],
    duration: float,
    step: float = 0.1,
) -> np.ndarray:
    count = max(1, int(np.ceil(duration / step)))
    votes = np.zeros((count, 2))
    for (start, end), label in zip(windows, labels, strict=True):
        i0 = max(0, int(start / step))
        i1 = min(count, int(np.ceil(end / step)))
        votes[i0:i1, label] += 1
    frames = np.zeros(count, dtype=int)
    spoken = votes.sum(axis=1) > 0
    frames[spoken] = np.argmax(votes, axis=1)[spoken]
    return frames


def _turns_for_phrases(
    phrases: list[tuple[float, float]],
    frames: np.ndarray,
    step: float = 0.1,
) -> list[tuple[float, float, int]]:
    """Keep a phrase whole when one voice dominates it. Split only a real change."""
    turns: list[tuple[float, float, int]] = []
    for start, end in phrases:
        i0 = max(0, int(start / step))
        i1 = min(len(frames), max(i0 + 1, int(np.ceil(end / step))))
        piece = frames[i0:i1]
        if len(piece) == 0:
            continue
        share = float(np.mean(piece == 1))
        if share <= 0.3:
            turns.append((start, end, 0))
        elif share >= 0.7:
            turns.append((start, end, 1))
        else:
            boundary = int(np.argmax(piece != piece[0]))
            cut = start + boundary * step
            if cut - start >= 0.4 and end - cut >= 0.4:
                turns.append((start, cut, int(piece[0])))
                turns.append((cut, end, int(piece[boundary])))
            else:
                turns.append((start, end, int(np.bincount(piece).argmax())))

    folded: list[tuple[float, float, int]] = []
    for start, end, label in turns:
        if folded and end - start < 0.7 and start - folded[-1][1] < 0.5:
            prev_start, _, prev_label = folded[-1]
            folded[-1] = (prev_start, end, prev_label)
        else:
            folded.append((start, end, label))
    return folded


def timeline_turns(
    windows: list[tuple[float, float]],
    labels: list[int],
    duration: float,
    step: float = 0.1,
) -> list[tuple[float, float, int]]:
    """One speaker per moment: overlapping windows vote, then short flips are removed."""
    count = max(1, int(np.ceil(duration / step)))
    votes = np.zeros((count, 2))
    for (start, end), label in zip(windows, labels, strict=True):
        i0 = max(0, int(start / step))
        i1 = min(count, int(np.ceil(end / step)))
        votes[i0:i1, label] += 1

    sequence = np.full(count, -1, dtype=int)
    spoken = votes.sum(axis=1) > 0
    sequence[spoken] = np.argmax(votes, axis=1)[spoken]

    radius = int(0.3 / step)
    cleaned = sequence.copy()
    for index in range(count):
        if sequence[index] < 0:
            continue
        around = sequence[max(0, index - radius) : index + radius + 1]
        around = around[around >= 0]
        if len(around) and np.mean(around == sequence[index]) < 0.5:
            cleaned[index] = int(np.bincount(around).argmax())

    turns: list[tuple[float, float, int]] = []
    index = 0
    while index < count:
        if cleaned[index] < 0:
            index += 1
            continue
        label = int(cleaned[index])
        end = index
        while end < count and cleaned[end] == label:
            end += 1
        turns.append((index * step, min(duration, end * step), label))
        index = end
    return turns


def separate_speakers(path: Path | str, out_dir: Path | str) -> dict[SpeakerRole, Path]:
    """Write manager.wav and client.wav (16 kHz) with each speaker kept in time."""
    path = Path(path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    mono_path = out_dir / "mono.wav"
    audio = load_mono_16k(path)
    sf.write(mono_path, audio, SAMPLE_RATE, subtype="PCM_16")

    voiced = speech_segments(mono_path)
    segments = speech_windows(voiced)
    embeddings = []
    for start, end in segments:
        i0 = int(round(start * SAMPLE_RATE))
        i1 = int(round(end * SAMPLE_RATE))
        embeddings.append(_embed(audio[i0:i1]))

    labels = label_segments(segments, embeddings)
    frame = _speaker_frames(segments, labels, duration=len(audio) / SAMPLE_RATE)
    turns = _turns_for_phrases(voiced, frame)

    written: dict[SpeakerRole, Path] = {}
    for role, speaker_id in ((SpeakerRole.MANAGER, 0), (SpeakerRole.CLIENT, 1)):
        track = np.zeros_like(audio)
        for start, end, label in turns:
            if label != speaker_id:
                continue
            i0 = int(round(start * SAMPLE_RATE))
            i1 = int(round(end * SAMPLE_RATE))
            track[i0:i1] = audio[i0:i1]
        dest = out_dir / f"{role.value}.wav"
        sf.write(dest, track, SAMPLE_RATE, subtype="PCM_16")
        written[role] = dest
    return written
