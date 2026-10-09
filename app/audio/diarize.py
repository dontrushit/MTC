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
MIN_EMBED_SEC = 0.6
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


def _kmeans2(vectors: np.ndarray) -> np.ndarray:
    """Two clusters on L2-normalized rows. Returns 0/1 labels."""
    first = vectors[0]
    second = vectors[int(np.argmin(vectors @ first))]
    labels = np.zeros(len(vectors), dtype=int)
    for _ in range(25):
        score = np.stack([vectors @ first, vectors @ second], axis=1)
        labels = np.argmax(score, axis=1)
        if labels.min() == labels.max():
            break
        updated = []
        for center_id, center in ((0, first), (1, second)):
            group = vectors[labels == center_id]
            mean = group.mean(axis=0)
            mean = mean / np.linalg.norm(mean)
            updated.append(mean)
        if np.allclose(updated[0], first) and np.allclose(updated[1], second):
            break
        first, second = updated
    return labels


def label_segments(
    segments: list[tuple[float, float]],
    embeddings: list[np.ndarray | None],
) -> list[int]:
    """Label each segment 0 or 1. Speaker 0 is whoever starts the call."""
    usable = [(index, vector) for index, vector in enumerate(embeddings) if vector is not None]
    if len(usable) < 2:
        return [0] * len(segments)

    vectors = np.stack([vector for _, vector in usable])
    raw = _kmeans2(vectors)
    if raw.min() == raw.max():
        return [0] * len(segments)

    centroid = []
    for cluster in (0, 1):
        mean = vectors[raw == cluster].mean(axis=0)
        centroid.append(mean / np.linalg.norm(mean))
    if float(centroid[0] @ centroid[1]) > SAME_SPEAKER_SIMILARITY:
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


def separate_speakers(path: Path | str, out_dir: Path | str) -> dict[SpeakerRole, Path]:
    """Write manager.wav and client.wav (16 kHz) with each speaker kept in time."""
    path = Path(path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    mono_path = out_dir / "mono.wav"
    audio = load_mono_16k(path)
    sf.write(mono_path, audio, SAMPLE_RATE, subtype="PCM_16")

    segments = speech_segments(mono_path)
    embeddings = []
    for start, end in segments:
        i0 = int(round(start * SAMPLE_RATE))
        i1 = int(round(end * SAMPLE_RATE))
        embeddings.append(_embed(audio[i0:i1]))

    labels = label_segments(segments, embeddings)
    turns = merge_labeled(segments, labels)

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
