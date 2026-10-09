#!/usr/bin/env python3
"""Generate a stereo Russian test call under data/raw/test_call.wav."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
OUT_WAV = RAW_DIR / "test_call.wav"
OUT_TXT = RAW_DIR / "test_call.txt"

PAUSE_SEC = 0.8

DIALOG: list[tuple[str, str]] = [
    (
        "manager",
        "Добрый день, компания МТС, меня зовут Анна. "
        "Мы обсуждали поставку оборудования для вашего офиса.",
    ),
    ("client", "Да, Анна, мы готовы двигаться дальше, если условия нас устроят."),
    (
        "manager",
        "Отлично. Я подготовлю коммерческое предложение и вышлю его вам до пятницы.",
    ),
    (
        "client",
        "Хорошо. Мы со своей стороны оплатим сто пятьдесят тысяч рублей до двадцатого числа.",
    ),
    (
        "manager",
        "Договорились. Завтра в одиннадцать перезвоню, чтобы уточнить детали доставки.",
    ),
    ("client", "Спасибо, буду ждать звонка и коммерческое предложение."),
]

SCENARIO_LINES = [
    "[manager] Добрый день... обсуждали поставку оборудования.",
    "[client] Готовы двигаться дальше при подходящих условиях.",
    "[manager] Вышлю коммерческое предложение до пятницы.",
    "[client] Оплатим 150 000 рублей до 20 числа.",
    "[manager] Завтра в 11 перезвоню по доставке.",
    "[client] Жду звонка и КП.",
]


def _pick_russian_voice() -> str:
    result = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, check=True)
    voices = result.stdout
    for name in ("Milena", "Yuri"):
        if name in voices:
            return name
    for line in voices.splitlines():
        if "ru_" in line or "Russian" in line:
            return line.split()[0]
    print(
        "No Russian macOS voice found (tried Milena, Yuri). "
        "Install a Russian voice in System Settings → Accessibility → Spoken Content.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def _run_ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", *args], capture_output=True, check=True)


def _say_to_wav(voice: str, text: str, out_wav: Path) -> None:
    with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as tmp:
        aiff = Path(tmp.name)
    try:
        subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
        _run_ffmpeg(
            ["-i", str(aiff), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(out_wav)]
        )
    finally:
        aiff.unlink(missing_ok=True)


def _silence_wav(duration_sec: float, out_wav: Path) -> None:
    _run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono",
            "-t",
            f"{duration_sec:.3f}",
            "-c:a",
            "pcm_s16le",
            str(out_wav),
        ]
    )


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def _concat_wavs(paths: list[Path], out_wav: Path) -> None:
    list_file = out_wav.with_suffix(".txt")
    lines = [f"file '{p.resolve()}'" for p in paths]
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        _run_ffmpeg(
            ["-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(out_wav)]
        )
    finally:
        list_file.unlink(missing_ok=True)


def _build_mono_timeline(turns: list[tuple[str, Path, float]], role: str, out_wav: Path) -> None:
    chunks: list[Path] = []
    for speaker, clip, duration in turns:
        if speaker == role:
            chunks.append(clip)
        else:
            silent = clip.with_name(f"sil_{clip.stem}.wav")
            _silence_wav(duration, silent)
            chunks.append(silent)
        pause = clip.with_name(f"pause_{clip.stem}.wav")
        _silence_wav(PAUSE_SEC, pause)
        chunks.append(pause)
    _concat_wavs(chunks, out_wav)


def main() -> int:
    voice = _pick_russian_voice()
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        turns: list[tuple[str, Path, float]] = []
        for i, (role, text) in enumerate(DIALOG):
            wav = tmp_path / f"turn_{i:02d}.wav"
            _say_to_wav(voice, text, wav)
            turns.append((role, wav, _probe_duration(wav)))

        manager_mono = tmp_path / "manager_timeline.wav"
        client_mono = tmp_path / "client_timeline.wav"
        _build_mono_timeline(turns, "manager", manager_mono)
        _build_mono_timeline(turns, "client", client_mono)

        _run_ffmpeg(
            [
                "-i",
                str(manager_mono),
                "-i",
                str(client_mono),
                "-filter_complex",
                "[0:a][1:a]amerge=inputs=2[aout]",
                "-map",
                "[aout]",
                "-c:a",
                "pcm_s16le",
                str(OUT_WAV),
            ]
        )

    OUT_TXT.write_text("\n".join(SCENARIO_LINES) + "\n", encoding="utf-8")
    duration = _probe_duration(OUT_WAV)
    print(f"Wrote {OUT_WAV} ({duration:.1f}s, voice={voice})")
    print(f"Scenario: {OUT_TXT}")
    if duration < 30 or duration > 60:
        print(f"Warning: duration {duration:.1f}s outside 30–60s target.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
