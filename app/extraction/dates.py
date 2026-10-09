"""Deterministic due-date resolution from spoken Russian phrases."""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

_WEEKDAYS: dict[str, int] = {
    "понедельник": 0,
    "понедельника": 0,
    "вторник": 1,
    "вторника": 1,
    "среда": 2,
    "среды": 2,
    "среду": 2,
    "четверг": 3,
    "четверга": 3,
    "пятница": 4,
    "пятницы": 4,
    "пятницу": 4,
    "суббота": 5,
    "субботы": 5,
    "субботу": 5,
    "воскресенье": 6,
    "воскресенья": 6,
}

_MONTHS_GEN: dict[str, int] = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


def _ref_date(ref: datetime, tz: ZoneInfo) -> date:
    if ref.tzinfo is None:
        return ref.date()
    return ref.astimezone(tz).date()


def _next_weekday_after(ref_d: date, weekday: int) -> date:
    """Nearest calendar day with given weekday strictly after ref_d."""
    days_ahead = (weekday - ref_d.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return ref_d + timedelta(days=days_ahead)


def _friday_of_week(ref_d: date, *, next_week: bool) -> date:
    """Friday of the ISO week containing ref_d, or the following week."""
    monday = ref_d - timedelta(days=ref_d.weekday())
    if next_week:
        monday += timedelta(days=7)
    return monday + timedelta(days=4)


def resolve_due(due_text: str | None, ref: datetime, tz: ZoneInfo) -> date | None:
    """Parse due_text relative to call start; return None if unrecognized."""
    if not due_text or not due_text.strip():
        return None

    text = due_text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    ref_d = _ref_date(ref, tz)

    if re.fullmatch(r"сегодня", text):
        return ref_d
    if re.fullmatch(r"завтра", text):
        return ref_d + timedelta(days=1)
    if re.fullmatch(r"послезавтра", text):
        return ref_d + timedelta(days=2)

    weekday_names = (
        "понедельник",
        "вторник",
        "среда",
        "среду",
        "среды",
        "четверг",
        "пятница",
        "пятницу",
        "пятницы",
        "суббота",
        "субботу",
        "субботы",
        "воскресенье",
        "воскресенья",
    )
    for name in weekday_names:
        if re.search(rf"(?:до|к|в)\s+{re.escape(name)}\b", text):
            return _next_weekday_after(ref_d, _WEEKDAYS[name])

    m = re.search(r"(?:до|к)\s+(\d{1,2})\s*числ", text)
    if m:
        day = int(m.group(1))
        if day < 1 or day > 31:
            return None
        if day > ref_d.day:
            year, month = ref_d.year, ref_d.month
        else:
            month = ref_d.month + 1
            year = ref_d.year
            if month > 12:
                month = 1
                year += 1
        last = calendar.monthrange(year, month)[1]
        day = min(day, last)
        return date(year, month, day)

    m = re.search(
        r"через\s+(\d+)\s+(день|дня|дней|недел[июи]|месяц|месяца|месяцев)",
        text,
    )
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit in ("день", "дня", "дней") or unit.startswith("дн"):
            return ref_d + timedelta(days=n)
        if unit.startswith("недел"):
            return ref_d + timedelta(weeks=n)
        if unit.startswith("месяц"):
            month = ref_d.month + n
            year = ref_d.year + (month - 1) // 12
            month = (month - 1) % 12 + 1
            last = calendar.monthrange(year, month)[1]
            return date(year, month, min(ref_d.day, last))

    if re.search(r"через\s+неделю", text):
        return ref_d + timedelta(weeks=1)

    if re.search(r"до\s+конца\s+недел", text):
        # Sunday of the current week
        return ref_d + timedelta(days=(6 - ref_d.weekday()))

    if re.search(r"до\s+конца\s+месяц", text):
        last = calendar.monthrange(ref_d.year, ref_d.month)[1]
        return date(ref_d.year, ref_d.month, last)

    if re.search(r"на\s+следующей\s+недел", text):
        return _friday_of_week(ref_d, next_week=True)
    if re.search(r"на\s+этой\s+недел", text):
        return _friday_of_week(ref_d, next_week=False)

    m = re.search(r"(\d{1,2})\s+(" + "|".join(_MONTHS_GEN) + r")", text)
    if m:
        day = int(m.group(1))
        month = _MONTHS_GEN[m.group(2)]
        year = ref_d.year
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if candidate <= ref_d:
            candidate = date(year + 1, month, day)
        return candidate

    m = re.search(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?", text)
    if m:
        day = int(m.group(1))
        month = int(m.group(2))
        year_s = m.group(3)
        if year_s:
            year = int(year_s)
            if year < 100:
                year += 2000
        else:
            year = ref_d.year
            try:
                candidate = date(year, month, day)
            except ValueError:
                return None
            if candidate < ref_d:
                year += 1
        try:
            return date(year, month, day)
        except ValueError:
            return None

    return None
