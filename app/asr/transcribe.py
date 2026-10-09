"""Channel-wise ASR with mlx-whisper and hallucination filtering."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import mlx_whisper

from app.audio.vad import speech_segments
from app.config import settings
from app.db.models import SpeakerRole


@dataclass(frozen=True)
class Segment:
    speaker: SpeakerRole
    start: float
    end: float
    text: str


def _vad_overlap_ratio(
    seg_start: float, seg_end: float, vad: list[tuple[float, float]]
) -> float:
    duration = seg_end - seg_start
    if duration <= 0:
        return 0.0
    overlap = 0.0
    for vs, ve in vad:
        o0 = max(seg_start, vs)
        o1 = min(seg_end, ve)
        if o1 > o0:
            overlap += o1 - o0
    return overlap / duration


def _keep_segment(raw: dict, vad: list[tuple[float, float]]) -> bool:
    text = (raw.get("text") or "").strip()
    if not text:
        return False
    no_speech = float(raw.get("no_speech_prob", 0.0))
    if no_speech > 0.6:
        return False
    compression = float(raw.get("compression_ratio", 0.0))
    if compression > 2.4:
        return False
    start = float(raw.get("start", 0.0))
    end = float(raw.get("end", 0.0))
    if _vad_overlap_ratio(start, end, vad) < 0.3:
        return False
    return True


def transcribe_channel(wav_path: Path | str, speaker: SpeakerRole) -> list[Segment]:
    """Transcribe one speaker channel; drop segments likely to be silence hallucinations."""
    wav_path = Path(wav_path)
    vad = speech_segments(wav_path)
    result = mlx_whisper.transcribe(
        str(wav_path),
        path_or_hf_repo=settings.WHISPER_MODEL,
        language="ru",
        condition_on_previous_text=False,
    )
    segments: list[Segment] = []
    for raw in result.get("segments") or []:
        if not _keep_segment(raw, vad):
            continue
        segments.append(
            Segment(
                speaker=speaker,
                start=float(raw["start"]),
                end=float(raw["end"]),
                text=(raw.get("text") or "").strip(),
            )
        )
    return segments
