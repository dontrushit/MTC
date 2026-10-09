#!/usr/bin/env python3
"""Transcribe a call file to stdout (no database). Stereo or a mixed phone recording."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from app.asr.merge import merge_dialog
from app.asr.roles import resolve_roles
from app.asr.transcribe import transcribe_channel
from app.audio.preprocess import prepare_channels
from app.audio.vad import speech_segments
from app.config import settings
from app.db.models import SpeakerRole


def _format_ts(sec: float) -> str:
    minutes = int(sec // 60)
    seconds = sec - minutes * 60
    return f"{minutes:02d}:{seconds:04.1f}"


def transcribe_path(path: Path) -> list[tuple[float, SpeakerRole, str]]:
    out_dir = settings.DATA_DIR / "processed" / f"cli_{path.stem}"
    channel_paths = prepare_channels(path, out_dir)

    speech_segments(channel_paths[SpeakerRole.MANAGER])
    speech_segments(channel_paths[SpeakerRole.CLIENT])

    segs_manager = transcribe_channel(channel_paths[SpeakerRole.MANAGER], SpeakerRole.MANAGER)
    segs_client = transcribe_channel(channel_paths[SpeakerRole.CLIENT], SpeakerRole.CLIENT)
    dialog = resolve_roles(merge_dialog(segs_manager, segs_client))
    return [(seg.start, seg.speaker, seg.text) for seg in dialog]


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <path-to-stereo-wav>", file=sys.stderr)
        return 1

    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        return 1

    started = time.perf_counter()
    lines = transcribe_path(path)
    elapsed = time.perf_counter() - started

    for start, speaker, text in lines:
        print(f"[{_format_ts(start)} {speaker.value}] {text}")

    print(f"\n# processed in {elapsed:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
