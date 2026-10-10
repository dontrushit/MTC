"""Which PBX call belongs on this employee's screen."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.atc.options import load_options
from app.atc.phones import normalize_phone
from app.db.models import AtcCall, Manager


def sees_atc(row: AtcCall, manager: Manager, session: Session) -> bool:
    """A call still waiting for a report is shown to the employee who answered."""
    agent = normalize_phone(row.agent_phone)
    own = normalize_phone(manager.phone)
    if agent:
        return agent == own
    options = load_options(session)
    if options.manager_id is not None:
        return options.manager_id == manager.id
    first = session.scalar(select(Manager.id).order_by(Manager.id))
    return first == manager.id
