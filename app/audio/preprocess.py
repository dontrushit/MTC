"""Split stereo call recordings into per-speaker mono WAV files."""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.audio.exceptions import MonoNotSupportedError
from app.audio.probe import probe
from app.db.models import SpeakerRole


def split_channels(path: Path | str, out_dir: Path | str) -> dict[SpeakerRole, Path]:
    """Extract ch0 (manager) and ch1 (client) as 16 kHz mono PCM s16le WAV."""
    path = Path(path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    info = probe(path)
    if info.channels < 2:
        raise MonoNotSupportedError(str(path))
    if info.channels > 2:
        msg = f"Expected stereo (2 channels), got {info.channels}: {path}"
        raise ValueError(msg)

    manager_path = out_dir / "manager.wav"
    client_path = out_dir / "client.wav"

    filter_graph = (
        "[0:a]channelsplit=channel_layout=stereo[FL][FR];"
        "[FL]aformat=sample_fmts=s16:channel_layouts=mono,aresample=16000[m];"
        "[FR]aformat=sample_fmts=s16:channel_layouts=mono,aresample=16000[c]"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(path),
        "-filter_complex",
        filter_graph,
        "-map",
        "[m]",
        "-c:a",
        "pcm_s16le",
        str(manager_path),
        "-map",
        "[c]",
        "-c:a",
        "pcm_s16le",
        str(client_path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)

    return {
        SpeakerRole.MANAGER: manager_path,
        SpeakerRole.CLIENT: client_path,
    }
