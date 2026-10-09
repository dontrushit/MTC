#!/usr/bin/env python3
"""One-command check of a real call: probe -> transcript -> agreements -> report.

Usage:
    python scripts/check_call.py data/raw/call.wav --date 2026-10-09
    python scripts/check_call.py data/raw/call.mp3 --swap   # manager is on the right channel

Report is saved to data/results/<name>_<time>.md with an empty "Эталон" section to fill in.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extract_file import _parse_date  # noqa: E402
from transcribe_file import _format_ts, transcribe_path  # noqa: E402

from app.audio.layout import is_separated_stereo  # noqa: E402
from app.audio.probe import probe  # noqa: E402
from app.config import settings  # noqa: E402
from app.db.models import SpeakerRole, Utterance  # noqa: E402
from app.extraction.dates import resolve_due  # noqa: E402
from app.extraction.llm import ExtractionError, extract  # noqa: E402
from app.extraction.verify import verify_agreements  # noqa: E402

ROLE_RU = {"manager": "менеджер", "client": "клиент"}


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка настоящего звонка")
    parser.add_argument("audio", type=Path)
    parser.add_argument("--date", default=None, help="Дата звонка YYYY-MM-DD (по умолчанию сейчас)")
    parser.add_argument("--swap", action="store_true", help="Менеджер в правом канале")
    args = parser.parse_args()

    if not args.audio.exists():
        print(f"Файл не найден: {args.audio}")
        return 1

    info = probe(args.audio)
    separated = is_separated_stereo(args.audio)
    kind = "стерео, каналы разделены" if separated else "обычная запись, голоса разделяются"
    print(
        f"Файл: {args.audio.name} | каналов: {info.channels} ({kind}) | "
        f"длительность: {info.duration_sec:.0f} с | {info.sample_rate} Гц"
    )
    if not separated:
        print("Первый говорящий считается менеджером. Если роли перепутаны, добавьте --swap.")

    started = _parse_date(args.date) if args.date else datetime.now(UTC)
    tz = ZoneInfo(settings.TZ)
    print(f"Модель: {settings.OLLAMA_MODEL} | whisper: {settings.WHISPER_MODEL}\n")

    t0 = time.perf_counter()
    lines = transcribe_path(args.audio)
    t_asr = time.perf_counter() - t0
    if args.swap:
        other = {SpeakerRole.MANAGER: SpeakerRole.CLIENT, SpeakerRole.CLIENT: SpeakerRole.MANAGER}
        lines = [(start, other[speaker], text) for start, speaker, text in lines]

    dialog = [
        f"[{_format_ts(start)} {ROLE_RU[speaker.value]}] {text}" for start, speaker, text in lines
    ]
    print("\n".join(dialog))
    print(f"\n# расшифровка: {t_asr:.1f} с, реплик: {len(lines)}\n")

    utterances = [
        Utterance(call_id=0, speaker=speaker, start_sec=start, end_sec=start, text=text)
        for start, speaker, text in lines
    ]
    warnings = _ListHandler()
    logging.getLogger("app.extraction").addHandler(warnings)

    t0 = time.perf_counter()
    try:
        result = extract(utterances, started)
    except ExtractionError as exc:
        print(f"Извлечение не удалось: {exc}\nПроверьте `ollama list` и OLLAMA_MODEL в .env.")
        return 3
    t_llm = time.perf_counter() - t0
    verified = verify_agreements(utterances, result.agreements)

    rows: list[str] = []
    for i, ag in enumerate(verified, 1):
        due = resolve_due(ag.due_text, started, tz)
        due_iso = due.isoformat() if due else "дата не определена"
        due_col = f"{ag.due_text or '—'} → {due_iso}"
        rows.append(
            f"{i}. [{ROLE_RU[ag.responsible]}] {ag.action}\n"
            f"   срок: {due_col}\n"
            + (f"   сумма: {ag.amount}\n" if ag.amount else "")
            + (f"   условия: {ag.conditions}\n" if ag.conditions else "")
            + f"   цитата (реплика {ag.utterance_index}): «{ag.quote}»"
        )

    print(f"Договорённости: {len(verified)} (модель вернула {len(result.agreements)}), "
          f"извлечение: {t_llm:.1f} с\n")
    print("\n".join(rows) if rows else "— не найдено —")
    if warnings.messages:
        print("\nПредупреждения проверки:")
        print("\n".join(f"- {m}" for m in warnings.messages))

    out_dir = settings.DATA_DIR / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{args.audio.stem}_{datetime.now():%Y%m%d_%H%M%S}.md"
    out.write_text(
        f"# {args.audio.name}\n\n"
        f"- дата звонка: {started:%Y-%m-%d}\n- каналов: {info.channels}, "
        f"длительность: {info.duration_sec:.0f} с, swap: {args.swap}\n"
        f"- модель: {settings.OLLAMA_MODEL}, whisper: {settings.WHISPER_MODEL}\n"
        f"- время: расшифровка {t_asr:.1f} с, извлечение {t_llm:.1f} с\n\n"
        f"## Расшифровка\n\n" + "\n".join(dialog) + "\n\n"
        f"## Найдено системой ({len(verified)}, модель вернула {len(result.agreements)})\n\n"
        + ("\n".join(rows) if rows else "— не найдено —") + "\n\n"
        + ("## Предупреждения\n\n" + "\n".join(f"- {m}" for m in warnings.messages) + "\n\n"
           if warnings.messages else "")
        + "## Эталон (заполнить вручную: что на самом деле договорились)\n\n"
        "1. [кто] действие — срок — сумма\n\n"
        "## Ошибки расшифровки (если заметили)\n\n-\n",
        encoding="utf-8",
    )
    print(f"\nОтчёт: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
