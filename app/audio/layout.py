"""Decide whether a file is real stereo (separate speakers) or a mixed phone recording."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from app.audio.probe import probe

_SAMPLE_SECONDS = 20
_SAME_CHANNEL_CORR = 0.95


def _load_pcm(path: Path, channels: int, seconds: float) -> np.ndarray:
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-t",
        str(seconds),
        "-i",
        str(path),
        "-ac",
        str(channels),
        "-ar",
        "16000",
        "-f",
        "f32le",
        "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True, check=True)
    audio = np.frombuffer(result.stdout, dtype=np.float32)
    return audio.reshape(-1, channels)


def is_separated_stereo(path: Path | str) -> bool:
    """True when the two channels carry different signals (manager left, client right).

    A phone recording exported as stereo with identical channels is treated as mixed mono.
    """
    path = Path(path)
    info = probe(path)
    if info.channels != 2:
        return False

    stereo = _load_pcm(path, 2, min(_SAMPLE_SECONDS, max(info.duration_sec, 0.1)))
    left, right = stereo[:, 0], stereo[:, 1]
    left_rms = float(np.sqrt(np.mean(left**2)))
    right_rms = float(np.sqrt(np.mean(right**2)))
    louder = max(left_rms, right_rms)
    quieter = min(left_rms, right_rms)
    if louder < 1e-4 or quieter < louder * 0.05:
        return True

    corr = float(np.corrcoef(left, right)[0, 1])
    return corr < _SAME_CHANNEL_CORR
