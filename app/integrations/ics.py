"""A calendar event for one agreement, sent as an .ics file the client saves."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import settings

PRODID = "-//MTC//Agreements//RU"


def build_ics(
    *,
    agreement_id: int,
    action: str,
    client_name: str,
    responsible: str,
    due_date: date | None,
    due_text: str,
    amount: str | None,
    conditions: str | None,
    quote: str,
    fallback: datetime,
) -> str:
    """Build a one-event calendar. No due date means the call date."""
    start = due_date or fallback.astimezone(ZoneInfo(settings.TZ)).date()
    title = action.strip() or "Договорённость"
    if client_name.strip():
        title = f"{client_name.strip()}: {title}"
    description = _description(responsible, due_date, due_text, amount, conditions, quote)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:agreement-{agreement_id}@mtc.local",
        f"DTSTAMP:{_stamp(datetime.now(ZoneInfo(settings.TZ)))}",
        f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{(start + timedelta(days=1)).strftime('%Y%m%d')}",
        f"SUMMARY:{_escape(title)}",
        f"DESCRIPTION:{_escape(description)}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"


def _description(
    responsible: str,
    due_date: date | None,
    due_text: str,
    amount: str | None,
    conditions: str | None,
    quote: str,
) -> list[str]:
    parts: list[str] = []
    if responsible:
        parts.append(f"Ответственный: {responsible}")
    if due_date is not None:
        parts.append(f"Срок: {due_date.isoformat()}")
    elif due_text.strip():
        parts.append(f"Срок: {due_text.strip()}")
    if amount and str(amount).strip():
        parts.append(f"Сумма: {str(amount).strip()}")
    if conditions and str(conditions).strip():
        parts.append(f"Условия: {str(conditions).strip()}")
    if quote and quote.strip():
        parts.append(f"Цитата: «{quote.strip()}»")
    if not parts:
        parts.append("Договорённость из звонка")
    return "\n".join(parts)


def _stamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo(settings.TZ))
    return value.strftime("%Y%m%dT%H%M%SZ")


def _escape(text: str) -> str:
    cleaned = (text or "").replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "")
    cleaned = cleaned.replace(";", "\\;").replace(",", "\\,")
    return " ".join(cleaned.split())
