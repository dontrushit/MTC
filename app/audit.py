"""Access journal: who opened a call, its audio, or sent data outside."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AuditLog, Manager

ACTIONS = {
    "upload_call": "Загружает звонок",
    "open_call": "Открывает звонок",
    "listen_audio": "Слушает запись",
    "download_ics": "Скачивает событие в календарь",
    "send_crm": "Отправляет в CRM",
    "consent": "Отмечает согласие на запись",
    "create_agreement": "Создаёт договорённость",
    "edit_agreement": "Правит договорённость",
    "delete_agreement": "Удаляет договорённость",
    "download_audio": "Скачивает запись",
}


def log(
    session: Session,
    *,
    manager: Manager | None,
    action: str,
    entity: str,
    entity_id: int | None,
    detail: str = "",
) -> None:
    session.add(
        AuditLog(
            at=datetime.now(UTC),
            manager_id=manager.id if manager is not None else None,
            manager_name=(manager.name if manager is not None else "") or "система",
            action=action,
            entity=entity,
            entity_id=entity_id,
            detail=detail,
        )
    )
    session.flush()


def recent(session: Session, limit: int = 100) -> list[AuditLog]:
    rows = list(
        session.scalars(
            select(AuditLog).order_by(AuditLog.at.desc(), AuditLog.id.desc()).limit(limit)
        ).all()
    )
    return rows


def action_ru(action: str) -> str:
    return ACTIONS.get(action, action)


def as_dict(row: AuditLog) -> dict:
    tz = ZoneInfo(settings.TZ)
    at = row.at
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return {
        "id": row.id,
        "at": at.astimezone(tz).isoformat(),
        "manager_id": row.manager_id,
        "manager_name": row.manager_name,
        "action": row.action,
        "entity": row.entity,
        "entity_id": row.entity_id,
        "detail": row.detail,
    }
