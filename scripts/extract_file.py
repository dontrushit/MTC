#!/usr/bin/env python3
"""Transcribe a stereo call and extract agreements (no database)."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import settings
from app.db.models import Utterance
from app.extraction.dates import resolve_due
from app.extraction.llm import extract
from app.extraction.verify import verify_agreements

sys.path.insert(0, str(Path(__file__).resolve().parent))
from transcribe_file import transcribe_path  # noqa: E402


def _parse_date(s: str) -> datetime:
    if "T" in s or "+" in s or s.endswith("Z"):
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    d = datetime.strptime(s, "%Y-%m-%d")
    tz = ZoneInfo(settings.TZ)
    return d.replace(tzinfo=tz)


def main() -> int:
    parser = argparse.ArgumentParser(description="Transcribe WAV and extract agreements")
    parser.add_argument("wav", type=str, help="Path to stereo WAV")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Call start (YYYY-MM-DD or ISO datetime); default: now",
    )
    args = parser.parse_args()

    if args.date:
        call_started = _parse_date(args.date)
    else:
        call_started = datetime.now(UTC)

    lines = transcribe_path(Path(args.wav))
    utterances = [
        Utterance(
            call_id=0,
            speaker=speaker,
            start_sec=start,
            end_sec=start + 1.0,
            text=text,
        )
        for start, speaker, text in lines
    ]

    tz = ZoneInfo(settings.TZ)
    result = extract(utterances, call_started)
    verified = verify_agreements(utterances, result.agreements)

    headers = ("ответственный", "действие", "срок", "сумма", "цитата")
    col_widths = [12, 28, 24, 14, 50]
    row_fmt = " | ".join(f"{{:{w}}}" for w in col_widths)
    print(row_fmt.format(*headers))
    print("-" * (sum(col_widths) + 3 * (len(headers) - 1)))

    for ag in verified:
        due_date = resolve_due(ag.due_text, call_started, tz)
        due_col = ag.due_text or ""
        if due_date:
            due_col = f"{due_col} -> {due_date.isoformat()}" if due_col else due_date.isoformat()
        print(
            row_fmt.format(
                ag.responsible[:col_widths[0]],
                (ag.action or "")[:col_widths[1]],
                due_col[:col_widths[2]],
                (ag.amount or "")[:col_widths[3]],
                (ag.quote or "")[:col_widths[4]],
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
