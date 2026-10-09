"""Russian labels and small formatters for the Streamlit UI."""

from __future__ import annotations

from datetime import datetime

CALL_STATUS_RU = {
    "new": "новый",
    "processing": "обрабатывается",
    "transcribed": "расшифрован",
    "extracted": "извлечено",
    "error": "ошибка",
}

AGREEMENT_STATUS_RU = {
    "open": "открыта",
    "overdue": "просрочена",
    "done": "выполнена",
    "cancelled": "отменена",
}

RESPONSIBLE_RU = {
    "manager": "менеджер",
    "client": "клиент",
}


def call_status_ru(status: str) -> str:
    return CALL_STATUS_RU.get(status, status)


def agreement_status_ru(status: str) -> str:
    return AGREEMENT_STATUS_RU.get(status, status)


def responsible_ru(responsible: str) -> str:
    return RESPONSIBLE_RU.get(responsible, responsible)


def format_dt(value: str | None) -> str:
    if not value:
        return "—"
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return value
    return parsed.strftime("%d.%m.%Y %H:%M")


def format_clock(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def format_percent(value: float | None) -> str:
    if value is None:
        return "—"
    if float(value).is_integer():
        return f"{int(value)}%"
    return f"{value:.1f}%"
