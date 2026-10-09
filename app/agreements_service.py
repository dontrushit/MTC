"""Agreement status maintenance shared by the API and, later, the bot."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Agreement, AgreementStatus


def mark_overdue(session: Session, today: date) -> int:
    """Move open agreements with due_date before today to overdue.

    Agreements due today stay open. Rows without a due date are left unchanged.
    The caller owns the transaction.
    """
    rows = session.scalars(
        select(Agreement).where(
            Agreement.status == AgreementStatus.OPEN,
            Agreement.due_date.is_not(None),
            Agreement.due_date < today,
        )
    ).all()
    now = datetime.now(UTC)
    for row in rows:
        row.status = AgreementStatus.OVERDUE
        row.updated_at = now
    return len(rows)
