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
