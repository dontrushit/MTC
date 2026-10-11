"""Telegram foundation: link tokens, the 'report ready' notify, and the bot."""

from __future__ import annotations

import hashlib
import json
import secrets
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import log as audit_log
from app.config import settings
from app.db.models import Manager, TgLinkToken

TELEGRAM_API = "https://api.telegram.org"
SEND_TIMEOUT = 5.0
SEND_RETRIES = 2


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_link_token(session: Session, manager: Manager) -> str:
    """One-time token for the /start command in the bot."""
    raw = secrets.token_urlsafe(16)
    session.add(
        TgLinkToken(
            token_hash=_hash(raw),
            manager_id=manager.id,
            expires_at=None,
        )
    )
    session.flush()
    return raw


def link_url(raw: str) -> str:
    username = settings.TELEGRAM_BOT_USERNAME.strip().lstrip("@")
    if username:
        return f"https://t.me/{username}?start={raw}"
    return f"https://t.me/?start={raw}"


def consume_token(session: Session, raw: str) -> Manager | None:
    """Valid token → the manager behind it; marks the token as used."""
    row = session.scalar(select(TgLinkToken).where(TgLinkToken.token_hash == _hash(raw)))
    if row is None or row.used_at is not None:
        return None
    expires = row.expires_at
    if expires is not None:
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires < datetime.now(UTC):
            return None
    row.used_at = datetime.now(UTC)
    session.flush()
    return session.get(Manager, row.manager_id)


def notify_report_ready(session: Session, call_id: int) -> None:
    """Tell the employee their report is ready. No personal data in the text.

    Silently off without TELEGRAM_BOT_TOKEN; Telegram failures never break
    the call pipeline (try/except, 5 s timeout, 2 retries).
    """
    try:
        token = settings.TELEGRAM_BOT_TOKEN.strip()
        if not token:
            return
        manager, count, soonest = _collect(session, call_id)
        if manager is None or not (manager.telegram_chat_id or "").strip():
            audit_log(
                session,
                manager=None,
                action="notify",
                entity="call",
                entity_id=call_id,
                detail="нет chat_id у сотрудника",
            )
            session.flush()
            return
        text = _message(call_id, count, soonest)
        link = settings.PUBLIC_BASE_URL.strip().rstrip("/")
        if link:
            text += f". Открыть: {link}"
        sent = _send(manager.telegram_chat_id.strip(), token, text)
        audit_log(
            session,
            manager=None,
            action="notify",
            entity="call",
            entity_id=call_id,
            detail="отправлено в Telegram" if sent else "не отправено",
        )
        session.flush()
    except Exception:  # noqa: BLE001 — уведомления не ломают пайплайн
        return


def _collect(session: Session, call_id: int):
    from app.db.models import Agreement, AgreementStatus, Call

    call = session.get(Call, call_id)
    if call is None:
        return None, 0, None
    manager = session.get(Manager, call.manager_id)
    agreements = list(
        session.scalars(select(Agreement).where(Agreement.call_id == call_id)).all()
    )
    dates = sorted(
        item.due_date
        for item in agreements
        if item.due_date is not None and item.status == AgreementStatus.OPEN
    )
    return manager, len(agreements), dates[0] if dates else None


def _message(call_id: int, count: int, soonest) -> str:
    due = f". Ближайший срок: {soonest.isoformat()}" if soonest is not None else ""
    return f"Отчёт по звонку #{call_id} готов. Договорённостей: {count}{due}"


def _send(chat_id: str, token: str, text: str) -> bool:
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    request = urllib.request.Request(
        f"{TELEGRAM_API}/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(SEND_RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=SEND_TIMEOUT) as response:
                if 200 <= response.status < 300:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt == SEND_RETRIES - 1:
                return False
            _ = exc
    return False


def scripts_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts"
