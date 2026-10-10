"""Channel-wise ASR with hallucination filtering (mlx-whisper or faster-whisper)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from app.asr.backend import transcribe_audio
from app.audio.vad import speech_segments
from app.db.models import SpeakerRole

SAMPLE_RATE = 16000
VAD_MERGE_GAP_SEC = 0.3
CHUNK_PAD_SEC = 0.2


@dataclass(frozen=True)
class Segment:
    speaker: SpeakerRole
    start: float
    end: float
    text: str


def merge_vad_intervals(
    intervals: list[tuple[float, float]],
    gap_sec: float = VAD_MERGE_GAP_SEC,
) -> list[tuple[float, float]]:
    """Merge adjacent VAD intervals when pause between them is below gap_sec."""
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda x: x[0])
    merged: list[tuple[float, float]] = [ordered[0]]
    for start, end in ordered[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end < gap_sec:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def _keep_whisper_segment(raw: dict) -> bool:
    text = (raw.get("text") or "").strip()
    if not text:
        return False
    no_speech = float(raw.get("no_speech_prob", 0.0))
    if no_speech > 0.6:
        return False
    compression = float(raw.get("compression_ratio", 0.0))
    if compression > 2.4:
        return False
    return True


def _text_from_whisper_result(result: dict) -> str:
    parts: list[str] = []
    for raw in result.get("segments") or []:
        if not _keep_whisper_segment(raw):
            continue
        parts.append((raw.get("text") or "").strip())
    return " ".join(parts).strip()


def transcribe_channel(wav_path: Path | str, speaker: SpeakerRole) -> list[Segment]:
    """Transcribe one speaker channel per merged VAD chunk."""
    wav_path = Path(wav_path)
    audio, sample_rate = sf.read(str(wav_path), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sample_rate != SAMPLE_RATE:
        msg = f"Expected {SAMPLE_RATE} Hz mono WAV, got {sample_rate} Hz: {wav_path}"
        raise ValueError(msg)

    duration_sec = len(audio) / SAMPLE_RATE
    vad_chunks = merge_vad_intervals(speech_segments(wav_path))

    segments: list[Segment] = []
    for chunk_start, chunk_end in vad_chunks:
        pad_start = max(0.0, chunk_start - CHUNK_PAD_SEC)
        pad_end = min(duration_sec, chunk_end + CHUNK_PAD_SEC)
        i0 = int(round(pad_start * SAMPLE_RATE))
        i1 = int(round(pad_end * SAMPLE_RATE))
        chunk = np.ascontiguousarray(audio[i0:i1], dtype=np.float32)

        result = transcribe_audio(chunk)
        text = _text_from_whisper_result(result)
        if not text:
            continue
        segments.append(
            Segment(
                speaker=speaker,
                start=chunk_start,
                end=chunk_end,
                text=text,
            )
        )
    return segments
