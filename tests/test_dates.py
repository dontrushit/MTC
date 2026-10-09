"""Tests for deterministic due-date resolution."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.extraction.dates import resolve_due

TZ = ZoneInfo("Europe/Moscow")
REF = datetime(2026, 10, 9, 14, 0, tzinfo=TZ)


@pytest.mark.parametrize(
    ("due_text", "expected"),
    [
        ("сегодня", "2026-10-09"),
        ("завтра", "2026-10-10"),
        ("послезавтра", "2026-10-11"),
        ("до пятницы", "2026-10-16"),
        ("до 20 числа", "2026-10-20"),
        ("до 5 числа", "2026-11-05"),
        ("через неделю", "2026-10-16"),
        ("через 3 дня", "2026-10-12"),
        ("до конца месяца", "2026-10-31"),
        ("15 ноября", "2026-11-15"),
        ("20.10", "2026-10-20"),
        ("20.10.2026", "2026-10-20"),
        ("на этой неделе", "2026-10-09"),
        ("на следующей неделе", "2026-10-16"),
        ("когда-нибудь потом", None),
        ("", None),
        (None, None),
    ],
)
def test_resolve_due(due_text: str | None, expected: str | None) -> None:
    result = resolve_due(due_text, REF, TZ)
    if expected is None:
        assert result is None
    else:
        assert result is not None
        assert result.isoformat() == expected


def test_resolve_due_utc_ref_converted_to_tz() -> None:
    ref_utc = datetime(2026, 10, 9, 21, 0, tzinfo=UTC)
    assert resolve_due("завтра", ref_utc, TZ).isoformat() == "2026-10-11"
