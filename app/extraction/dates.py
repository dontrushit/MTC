"""Deterministic due-date resolution from spoken Russian phrases."""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.extraction.numerals import normalize_spoken_numerals

_WEEKDAYS: dict[str, int] = {
    "понедельник": 0,
    "понедельника": 0,
    "понедельнику": 0,
    "вторник": 1,
    "вторника": 1,
    "вторнику": 1,
    "среда": 2,
    "среды": 2,
    "среду": 2,
    "среде": 2,
    "четверг": 3,
    "четверга": 3,
    "четвергу": 3,
    "пятница": 4,
    "пятницы": 4,
    "пятницу": 4,
    "пятнице": 4,
    "суббота": 5,
    "субботы": 5,
    "субботу": 5,
    "субботе": 5,
    "воскресенье": 6,
    "воскресенья": 6,
    "воскресенью": 6,
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

_MONTHS_ALT = "|".join(_MONTHS_GEN)
_WEEKDAY_ALT = "|".join(re.escape(k) for k in _WEEKDAYS)


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


def _sunday_of_week(ref_d: date) -> date:
    return ref_d + timedelta(days=(6 - ref_d.weekday()))


def _monday_next_week(ref_d: date) -> date:
    monday = ref_d - timedelta(days=ref_d.weekday())
    return monday + timedelta(days=7)


def _weekday_in_next_week(ref_d: date, weekday: int) -> date:
    return _monday_next_week(ref_d) + timedelta(days=weekday)


def _day_of_month(ref_d: date, day: int) -> date | None:
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


def _add_months(ref_d: date, months: int) -> date:
    month = ref_d.month + months
    year = ref_d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(ref_d.day, last))


def _text_has_month(text: str) -> bool:
    return bool(re.search(rf"\b(?:{_MONTHS_ALT})\b", text))


def _date_from_day_month(day: int, month: int, ref_d: date) -> date | None:
    if day < 1 or day > 31:
        return None
    year = ref_d.year
    try:
        candidate = date(year, month, day)
    except ValueError:
        return None
    if candidate <= ref_d:
        try:
            candidate = date(year + 1, month, day)
        except ValueError:
            return None
    return candidate


def _parse_explicit_month(text: str, ref_d: date) -> date | None:
    """Parse phrases with a month name; None if month present but phrase is invalid."""
    if not _text_has_month(text):
        return None

    m = re.search(rf"(?:до|к)\s*(\d{{1,2}})\s+(?:{_MONTHS_ALT})\b", text)
    if m:
        month_word = re.search(rf"\b(?:{_MONTHS_ALT})\b", text[m.start() :])
        if month_word is None:
            return None
        month = _MONTHS_GEN[month_word.group(0)]
        return _date_from_day_month(int(m.group(1)), month, ref_d)

    m = re.search(rf"(\d{{1,2}})\s+(?:{_MONTHS_ALT})\b", text)
    if m:
        month_word = re.search(rf"\b(?:{_MONTHS_ALT})\b", text[m.start() :])
        if month_word is None:
            return None
        month = _MONTHS_GEN[month_word.group(0)]
        return _date_from_day_month(int(m.group(1)), month, ref_d)

    return None


def _weekday_from_token(token: str) -> int | None:
    token = token.lower()
    if token in _WEEKDAYS:
        return _WEEKDAYS[token]
    for name, wd in _WEEKDAYS.items():
        if token.startswith(name[:4]) or name.startswith(token[:4]):
            return wd
    return None


def _this_or_next_weekday(ref_d: date, weekday: int) -> date:
    days_ahead = weekday - ref_d.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return ref_d + timedelta(days=days_ahead)


def _end_of_quarter(ref_d: date) -> date:
    q_end_month = ((ref_d.month - 1) // 3 + 1) * 3
    last = calendar.monthrange(ref_d.year, q_end_month)[1]
    return date(ref_d.year, q_end_month, last)


def resolve_due(due_text: str | None, ref: datetime, tz: ZoneInfo) -> date | None:
    """Parse due_text relative to call start; return None if unrecognized."""
    if not due_text or not due_text.strip():
        return None

    text = normalize_spoken_numerals(due_text.strip())
    text = re.sub(r"\s+", " ", text)
    ref_d = _ref_date(ref, tz)

    if re.search(r"\bсегодня\b", text):
        return ref_d
    if re.search(r"\bзавтра\b", text):
        return ref_d + timedelta(days=1)
    if re.search(r"\bпослезавтра\b", text):
        return ref_d + timedelta(days=2)

    if _text_has_month(text):
        month_date = _parse_explicit_month(text, ref_d)
        return month_date

    if re.search(r"в\s+течение\s+дня", text):
        return ref_d

    if re.search(r"в\s+начале\s+следующей\s+недел", text):
        return _monday_next_week(ref_d)

    m = re.search(
        r"на\s+следующей\s+недел[еи]\s+(?:в\s+)?("
        + "|".join(re.escape(k) for k in _WEEKDAYS)
        + r")\b",
        text,
    )
    if m:
        wd = _WEEKDAYS[m.group(1)]
        return _weekday_in_next_week(ref_d, wd)

    if re.search(r"(?:к|до)\s+конц[ау]\s+недел", text):
        return _sunday_of_week(ref_d)

    if re.search(r"в\s+течение\s+недел", text):
        return _next_weekday_after(ref_d, 4)

    if re.search(r"(?:к|до)\s+конц[ау]\s+месяц", text):
        last = calendar.monthrange(ref_d.year, ref_d.month)[1]
        return date(ref_d.year, ref_d.month, last)

    if re.search(r"(?:к|до)\s+конц[ау]\s+год", text):
        return date(ref_d.year, 12, 31)

    if re.search(r"(?:к|до)\s+конц[ау]\s+квартал", text):
        return _end_of_quarter(ref_d)

    m = re.search(rf"в\s+следующ(?:ую|ий|ее|ей)\s+({_WEEKDAY_ALT})\b", text)
    if m:
        wd = _weekday_from_token(m.group(1))
        if wd is not None:
            return _next_weekday_after(ref_d, wd)

    m = re.search(rf"в\s+эту\s+({_WEEKDAY_ALT})\b", text)
    if m:
        wd = _weekday_from_token(m.group(1))
        if wd is not None:
            return _this_or_next_weekday(ref_d, wd)

    weekday_names = tuple(_WEEKDAYS.keys())
    for name in weekday_names:
        if re.search(rf"(?:до|к|в)\s+{re.escape(name)}\b", text):
            return _next_weekday_after(ref_d, _WEEKDAYS[name])

    m = re.search(r"(?:до|к)\s+(\d{1,2})(?:\s*числ)?\b", text)
    if m:
        return _day_of_month(ref_d, int(m.group(1)))

    m = re.search(r"\b(\d{1,2})\s+числ\w*\b", text)
    if m:
        return _day_of_month(ref_d, int(m.group(1)))

    if re.search(r"через\s+полгода", text):
        return _add_months(ref_d, 6)

    if re.search(r"через\s+месяц\b", text):
        return _add_months(ref_d, 1)

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
            return _add_months(ref_d, n)

    if re.search(r"через\s+неделю", text):
        return ref_d + timedelta(weeks=1)

    if re.search(r"до\s+конца\s+недел", text):
        return _sunday_of_week(ref_d)

    if re.search(r"до\s+конца\s+месяц", text):
        last = calendar.monthrange(ref_d.year, ref_d.month)[1]
        return date(ref_d.year, ref_d.month, last)

    if re.search(r"на\s+следующей\s+недел", text):
        return _friday_of_week(ref_d, next_week=True)
    if re.search(r"на\s+этой\s+недел", text):
        return _friday_of_week(ref_d, next_week=False)

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
