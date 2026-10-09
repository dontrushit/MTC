"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session

from app.db import session as db_session


def get_db() -> Generator[Session, None, None]:
    """Yield a DB session and commit on success. Override this in tests."""
    session = db_session.SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
