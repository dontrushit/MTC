"""Database engine, session factory, and schema initialization."""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.models import Base

connect_args = {}
if settings.DB_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(settings.DB_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create all tables if they do not exist."""
    Base.metadata.create_all(bind=engine)
    _ensure_client_last_name()
    _ensure_call_report()
    _ensure_manager_phone()


def _ensure_client_last_name() -> None:
    """Add last_name to a database created before surname was stored."""
    if not settings.DB_URL.startswith("sqlite"):
        return
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(clients)")).fetchall()
        if not rows:
            return
        columns = {row[1] for row in rows}
        if "last_name" not in columns:
            conn.execute(
                text(
                    "ALTER TABLE clients ADD COLUMN last_name VARCHAR(255) "
                    "NOT NULL DEFAULT ''"
                )
            )


def _ensure_call_report() -> None:
    """Add the neural-network report columns to calls created before them."""
    if not settings.DB_URL.startswith("sqlite"):
        return
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(calls)")).fetchall()
        if not rows:
            return
        columns = {row[1] for row in rows}
        for name, ddl in (
            ("report_topic", "TEXT NOT NULL DEFAULT ''"),
            ("report_summary", "TEXT NOT NULL DEFAULT ''"),
            ("report_json", "TEXT NOT NULL DEFAULT '{}'"),
        ):
            if name not in columns:
                conn.execute(text(f"ALTER TABLE calls ADD COLUMN {name} {ddl}"))


def _ensure_manager_phone() -> None:
    """Add phone so an agent number from the PBX can be matched to a manager."""
    if not settings.DB_URL.startswith("sqlite"):
        return
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(managers)")).fetchall()
        if not rows:
            return
        columns = {row[1] for row in rows}
        if "phone" not in columns:
            conn.execute(text("ALTER TABLE managers ADD COLUMN phone VARCHAR(64)"))
