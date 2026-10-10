"""Passwords and browser sessions for employees. The PBX uses its own login."""

from __future__ import annotations

import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuthSession, Manager

_ROUNDS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ROUNDS)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or ":" not in stored:
        return False
    salt_hex, digest_hex = stored.split(":", 1)
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ROUNDS)
    return secrets.compare_digest(digest.hex(), digest_hex)


def needs_setup(session: Session) -> bool:
    """True until at least one employee has a password."""
    hashes = list(session.scalars(select(Manager.password_hash)).all())
    return not any(hashes)


def open_session(session: Session, manager: Manager) -> str:
    token = secrets.token_urlsafe(32)
    session.add(AuthSession(token_hash=_token_hash(token), manager_id=manager.id))
    session.flush()
    return token


def manager_from_token(session: Session, token: str) -> Manager | None:
    if not token:
        return None
    row = session.scalar(select(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
    if row is None:
        return None
    return session.get(Manager, row.manager_id)


def close_session(session: Session, token: str) -> None:
    row = session.scalar(select(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
    if row is not None:
        session.delete(row)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
