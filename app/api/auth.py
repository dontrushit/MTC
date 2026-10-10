"""Sign in, first password, and who is using the screen."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.guard import require_manager
from app.auth import (
    close_session,
    hash_password,
    needs_setup,
    open_session,
    verify_password,
)
from app.db.models import Manager

router = APIRouter(tags=["auth"])


class SetupIn(BaseModel):
    name: str = ""
    manager_id: int | None = None
    password: str = Field(min_length=4)


class LoginIn(BaseModel):
    name: str = Field(min_length=1)
    password: str = Field(min_length=1)


class ManagerBrief(BaseModel):
    id: int
    name: str


class AuthStatus(BaseModel):
    needs_setup: bool
    managers: list[ManagerBrief]


class AuthUser(BaseModel):
    id: int
    name: str
    is_supervisor: bool
    token: str = ""


def _brief(session: Session) -> list[ManagerBrief]:
    rows = session.scalars(select(Manager).order_by(Manager.name, Manager.id)).all()
    return [ManagerBrief(id=row.id, name=row.name) for row in rows]


def _user(manager: Manager, token: str = "") -> AuthUser:
    return AuthUser(
        id=manager.id,
        name=manager.name,
        is_supervisor=manager.is_supervisor,
        token=token,
    )


@router.get("/auth/status", response_model=AuthStatus)
def auth_status(db: Session = Depends(get_db)) -> AuthStatus:
    return AuthStatus(needs_setup=needs_setup(db), managers=_brief(db))


@router.post("/auth/setup", response_model=AuthUser)
def auth_setup(payload: SetupIn, db: Session = Depends(get_db)) -> AuthUser:
    """Set the first password. After that, only sign-in works."""
    if not needs_setup(db):
        raise HTTPException(status_code=400, detail="Пароль уже задан. Войдите.")
    if payload.manager_id is not None:
        manager = db.get(Manager, payload.manager_id)
        if manager is None:
            raise HTTPException(status_code=404, detail="Сотрудник не найден")
    else:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Нужно имя сотрудника")
        manager = Manager(name=name)
        db.add(manager)
        db.flush()
    manager.password_hash = hash_password(payload.password)
    if db.scalar(select(Manager.id).where(Manager.is_supervisor.is_(True))) is None:
        manager.is_supervisor = True
    token = open_session(db, manager)
    db.commit()
    return _user(manager, token)


@router.post("/auth/login", response_model=AuthUser)
def auth_login(payload: LoginIn, db: Session = Depends(get_db)) -> AuthUser:
    name = payload.name.strip()
    matches = list(db.scalars(select(Manager).where(Manager.name == name)).all())
    for manager in matches:
        if verify_password(payload.password, manager.password_hash):
            token = open_session(db, manager)
            db.commit()
            return _user(manager, token)
    raise HTTPException(status_code=401, detail="Неверное имя или пароль")


@router.get("/auth/me", response_model=AuthUser)
def auth_me(manager: Manager = Depends(require_manager)) -> AuthUser:
    return _user(manager)


@router.post("/auth/logout")
def auth_logout(request: Request, db: Session = Depends(get_db)) -> dict:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        close_session(db, header[7:].strip())
        db.commit()
    return {}
