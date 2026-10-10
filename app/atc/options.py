"""PBX settings saved in the database, with the environment as the fallback."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AppSetting

_USER = "atc_basic_user"
_PASSWORD = "atc_basic_password"
_RECORDING = "atc_recording_url"
_PUBLIC = "atc_public_url"
_MANAGER = "atc_manager_id"


@dataclass(frozen=True)
class AtcOptions:
    basic_user: str
    basic_password: str
    recording_url: str
    public_url: str
    manager_id: int | None

    @property
    def event_url(self) -> str:
        base = (self.public_url or settings.API_URL).strip().rstrip("/")
        return f"{base}/CallEvent"


def load_options(session: Session) -> AtcOptions:
    stored = {row.key: row.value for row in session.scalars(select(AppSetting)).all()}

    def pick(key: str, env: str) -> str:
        if key in stored:
            return stored[key]
        return env

    return AtcOptions(
        basic_user=pick(_USER, settings.ATC_BASIC_USER).strip(),
        basic_password=pick(_PASSWORD, settings.ATC_BASIC_PASSWORD),
        recording_url=pick(_RECORDING, settings.ATC_RECORDING_URL).strip(),
        public_url=pick(_PUBLIC, "").strip(),
        manager_id=_manager_id(pick(_MANAGER, settings.ATC_MANAGER_ID)),
    )


def save_options(
    session: Session,
    *,
    basic_user: str,
    basic_password: str,
    recording_url: str,
    public_url: str,
    manager_id: int | None,
) -> AtcOptions:
    _write(session, _USER, basic_user.strip())
    _write(session, _PASSWORD, basic_password)
    _write(session, _RECORDING, recording_url.strip())
    _write(session, _PUBLIC, public_url.strip().rstrip("/"))
    _write(session, _MANAGER, "" if manager_id is None else str(manager_id))
    return load_options(session)


def _write(session: Session, key: str, value: str) -> None:
    row = session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value))
        return
    row.value = value


def _manager_id(raw: str) -> int | None:
    text = raw.strip()
    if not text.isdigit():
        return None
    number = int(text)
    if number < 1:
        return None
    return number
