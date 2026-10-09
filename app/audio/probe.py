"""Probe audio files via ffprobe."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AudioInfo:
    channels: int
    duration_sec: float
    sample_rate: int


def probe(path: Path | str) -> AudioInfo:
    """Return channel count, duration, and sample rate for the first audio stream."""
    path = Path(path)
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)

    audio_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "audio"),
        None,
    )
    if audio_stream is None:
        msg = f"No audio stream found in {path}"
        raise ValueError(msg)

    channels = int(audio_stream.get("channels", 0))
    sample_rate = int(audio_stream.get("sample_rate", 0))

    duration_raw = data.get("format", {}).get("duration")
    if duration_raw is None:
        duration_raw = audio_stream.get("duration")
    duration_sec = float(duration_raw) if duration_raw is not None else 0.0

    return AudioInfo(channels=channels, duration_sec=duration_sec, sample_rate=sample_rate)
