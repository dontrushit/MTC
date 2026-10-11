#!/usr/bin/env python3
"""Generate the recording notice used by the Asterisk dialplan.

Result: services/ast/sounds/custom/notice.wav (8 kHz, mono, <= 6 s).
Throws no exception if TTS itself fails — asterisk keeps working with the
previous notice.wav. Text lives in the config (IVR_NOTICE_TEXT).

Usage: python scripts/make_notice.py [--out PATH]
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402

DEFAULT_OUT = ROOT / "services" / "ast" / "sounds" / "custom" / "notice.wav"


def synth_ru(text: str) -> bytes | None:
    """One sentence of Russian speech. None when no engine is available."""
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "notice.wav"
        rendered = False
        if platform.system() == "Darwin" and shutil.which("say"):
            rendered = (
                subprocess.run(
                    [
                        "say",
                        "-v",
                        "Milena",
                        "-o",
                        str(raw),
                        "--data-format=LEF32@16000",
                        text,
                    ],
                    check=False,
                ).returncode
                == 0
                and raw.is_file()
            )
        if not rendered:
            for engine in ("espeak-ng", "espeak"):
                binary = shutil.which(engine)
                if binary is None:
                    continue
                rendered = (
                    subprocess.run(
                        [binary, "-v", "ru", "-w", str(raw), text], check=False
                    ).returncode
                    == 0
                    and raw.is_file()
                )
                break
        if not rendered:
            voice = settings.IVR_PIPER_MODEL.strip()
            if voice and Path(voice).is_file():
                rendered = (
                    subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "piper",
                            "-m",
                            voice,
                            "--length-scale",
                            "0.82",
                            "-f",
                            str(raw),
                            text,
                        ],
                        check=False,
                    ).returncode
                    == 0
                    and raw.is_file()
                )
        if not rendered:
            return None
        # приводим к 8 кГц mono PCM16 и обрезаем 6 секунд
        out = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(raw),
                "-af",
                "silenceremove=start_periods=1:start_silence=0",
                "-t",
                "6",
                "-ar",
                "8000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                "file:%s" % (Path(tmp) / "out.wav"),
            ],
            capture_output=True,
            text=True,
        )
        final = Path(tmp) / "out.wav"
        if out.returncode == 0 and final.is_file() and final.stat().st_size > 0:
            return final.read_bytes()
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Notice audio for the PBX")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    text = settings.IVR_NOTICE_TEXT.strip()
    payload = synth_ru(text)
    if payload is None:
        print("Не удалось синтезировать уведомление.")
        return 1
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(payload)
    print(f"Уведомление сохранено: {out_path} ({len(payload)} байт)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
