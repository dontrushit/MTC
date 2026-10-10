"""Require an employee login on every route except the PBX webhook and sign-in."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.auth import manager_from_token
from app.db.models import Manager

_PUBLIC = {"/auth/status", "/auth/login", "/auth/setup", "/CallEvent"}


def require_manager(request: Request, db: Session = Depends(get_db)) -> Manager:
    """The employee behind the bearer token."""
    manager = _lookup(request, db)
    if manager is None:
        raise HTTPException(status_code=401, detail="Нужно войти")
    return manager


def require_supervisor(request: Request, db: Session = Depends(get_db)) -> Manager:
    manager = require_manager(request, db)
    if not manager.is_supervisor:
        raise HTTPException(status_code=403, detail="Это может менять ответственный сотрудник")
    return manager


def require_login(request: Request, db: Session = Depends(get_db)) -> None:
    if request.url.path in _PUBLIC:
        return
    if _lookup(request, db) is None:
        raise HTTPException(status_code=401, detail="Нужно войти")


def _lookup(request: Request, db: Session) -> Manager | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    return manager_from_token(db, header[7:].strip())
