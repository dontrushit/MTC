"""Whisper backends: mlx-whisper (Apple Silicon) and faster-whisper (CPU, Linux/Windows).

Both return whisper-style segment dicts with text, no_speech_prob and compression_ratio.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from app.config import settings


def _transcribe_mlx(audio: np.ndarray) -> list[dict]:
    import mlx_whisper

    result = mlx_whisper.transcribe(
        audio,
        path_or_hf_repo=settings.WHISPER_MODEL,
        language="ru",
        condition_on_previous_text=False,
    )
    return list(result.get("segments") or [])


@lru_cache(maxsize=1)
def _faster_model():
    from faster_whisper import WhisperModel

    return WhisperModel(
        settings.WHISPER_MODEL,
        device="cpu",
        compute_type="int8",
        cpu_threads=settings.ASR_CPU_THREADS,
    )


def _transcribe_faster(audio: np.ndarray) -> list[dict]:
    segments, _info = _faster_model().transcribe(
        audio,
        language="ru",
        beam_size=5,
        condition_on_previous_text=False,
        vad_filter=False,
    )
    return [
        {
            "text": s.text,
            "no_speech_prob": s.no_speech_prob,
            "compression_ratio": s.compression_ratio,
        }
        for s in segments
    ]


def transcribe_chunk(audio: np.ndarray) -> list[dict]:
    """Transcribe a 16 kHz mono float32 chunk with the configured backend."""
    if settings.ASR_BACKEND == "mlx":
        return _transcribe_mlx(audio)
    return _transcribe_faster(audio)
