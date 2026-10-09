"""Voice activity detection with Silero VAD."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import soundfile as sf
import torch
from silero_vad import get_speech_timestamps, load_silero_vad


@lru_cache(maxsize=1)
def _vad_model():
    return load_silero_vad()


def _load_wav_16k_mono(wav_path: Path) -> torch.Tensor:
    data, sample_rate = sf.read(str(wav_path), dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    if sample_rate != 16000:
        msg = f"Expected 16 kHz mono WAV, got {sample_rate} Hz: {wav_path}"
        raise ValueError(msg)
    return torch.from_numpy(data)


def speech_segments(wav_path: Path | str) -> list[tuple[float, float]]:
    """Return (start_sec, end_sec) intervals where speech is detected."""
    wav_path = Path(wav_path)
    model = _vad_model()
    wav = _load_wav_16k_mono(wav_path)
    timestamps = get_speech_timestamps(
        wav,
        model,
        sampling_rate=16000,
        return_seconds=True,
    )
    return [(float(t["start"]), float(t["end"])) for t in timestamps]
