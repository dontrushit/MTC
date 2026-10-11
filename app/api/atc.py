"""HTTP entry for MTS Автосекретарь. The answer is always empty and immediate."""

from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import worker
from app.api.deps import get_db
from app.api.guard import require_manager, require_supervisor
from app.atc.access import sees_atc
from app.atc.ast import ingest_ast_call, parse_metadata, pick_audio
from app.atc.options import load_options, save_options
from app.atc.phones import normalize_phone
from app.atc.service import fetch_and_attach, ingest_event, store_recording
from app.auth import hash_password
from app.db.models import AtcCall, AtcCallStatus, Manager

router = APIRouter(tags=["atc"])
_basic = HTTPBasic(auto_error=False)
_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}


class ManagerPhoneIn(BaseModel):
    id: int
    name: str = ""
    phone: str = ""
    password: str = ""


class AtcSettingsIn(BaseModel):
    public_url: str = ""
    basic_user: str = ""
    basic_password: str = ""
    recording_url: str = ""
    manager_id: int | None = None
    managers: list[ManagerPhoneIn] = []


class AtcSettingsOut(BaseModel):
    event_url: str
    public_url: str
    basic_user: str
    basic_password: str
    recording_url: str
    manager_id: int | None
    managers: list[dict]


class AtcLiveOut(BaseModel):
    phase: str
    caller_phone: str = ""
    external_id: str = ""
    recording_on: bool = False


class AtcCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    caller_phone: str
    agent_phone: str
    status: AtcCallStatus
    call_id: int | None
    note: str
    last_event: int | None


def require_atc(
    credentials: HTTPBasicCredentials | None = Depends(_basic),
    db: Session = Depends(get_db),
) -> None:
    """Check Basic Auth only after a login and password are saved."""
    options = load_options(db)
    user = options.basic_user
    password = options.basic_password
    if not user and not password:
        return
    if credentials is None or not _same(credentials.username, user) or not _same(
        credentials.password, password
    ):
        raise HTTPException(
            status_code=401,
            detail="Нужна авторизация АТС",
            headers={"WWW-Authenticate": "Basic"},
        )


def _same(left: str, right: str) -> bool:
    return secrets.compare_digest(left.encode("utf-8"), right.encode("utf-8"))

@router.post("/api/v1/process-audio")
async def process_ast_audio(
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    _: None = Depends(require_atc),
) -> dict:
    """Receive the ASTService webhook: one finished Asterisk/Linphone call."""
    try:
        form = await request.form()
    except Exception:
        return {"ok": True}
    files: dict[str, object] = {}
    for name in ("mixed", "caller_mono", "callee_mono", "stereo"):
        value = form.get(name)
        if value is not None and hasattr(value, "read"):
            files[name] = value
    available = {name: (b"pick" if name in files else None) for name in files}
    audio_name, _ = pick_audio(available)
    audio = b""
    extension = ".wav"
    chosen = files.get(audio_name)
    if chosen is not None and hasattr(chosen, "read"):
        audio = await chosen.read()
        original = Path(chosen.filename or "").suffix.lower()
        if original in _AUDIO_EXTENSIONS:
            extension = original
    result = ingest_ast_call(
        db,
        parse_metadata(form.get("metadata")),
        audio_name,
        audio,
        extension,
    )
    db.commit()
    if result.submit and result.call_id is not None:
        worker.submit_call(result.call_id)
    return {
        "ok": True,
        "call_id": result.call_id,
        "note": result.note,
        "audio": audio_name or "none",
    }


@router.post("/CallEvent")
async def call_event(
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    _: None = Depends(require_atc),
) -> dict:
    """Accept a CRM API event. Never returns a Transfer command."""
    try:
        payload = await request.json()
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    result = ingest_event(db, payload)
    db.commit()
    result = _mark_mts_consent(db, payload, result)
    if result.submit and result.call_id is not None:
        worker.submit_call(result.call_id)
    elif result.fetch and result.external_id:
        background.add_task(fetch_and_attach, result.external_id)
    return {}


def _mark_mts_consent(db: Session, payload: dict, result) -> object:
    """The operator marks that it announced the recording — then consent is auto."""
    from datetime import UTC, datetime

    from app.audit import log as audit_log
    from app.db.models import Call

    told = next(
        (
            value
            for key in ("RecordNotice", "NoticePlayed", "notice_played")
            for value in [payload.get(key)]
            if value is not None
        ),
        None,
    )
    if told is None or result.call_id is None:
        return result
    truthy = told is True or str(told).strip().lower() in {"1", "true", "yes", "on"}
    if not truthy:
        return result
    call = db.get(Call, result.call_id)
    if call is None or call.consent:
        return result
    call.consent = True
    call.consent_source = "ivr_mts"
    call.consent_at = datetime.now(UTC)
    audit_log(
        db,
        manager=None,
        action="consent",
        entity="call",
        entity_id=call.id,
        detail="автоматическое уведомление АТС (ivr_mts)",
    )
    db.commit()
    return result


@router.get("/atc/settings", response_model=AtcSettingsOut)
def get_atc_settings(
    db: Session = Depends(get_db),
    _: Manager = Depends(require_supervisor),
) -> AtcSettingsOut:
    return _settings_out(db)


@router.put("/atc/settings", response_model=AtcSettingsOut)
def update_atc_settings(
    payload: AtcSettingsIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    _: Manager = Depends(require_supervisor),
) -> AtcSettingsOut:
    if payload.manager_id is not None and db.get(Manager, payload.manager_id) is None:
        raise HTTPException(status_code=400, detail="Пользователь не найден")
    for item in payload.managers:
        manager = db.get(Manager, item.id)
        if manager is None:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        name = item.name.strip()
        if name:
            manager.name = name
        elif not manager.name.strip():
            raise HTTPException(status_code=400, detail="Нужно имя сотрудника")
        manager.phone = normalize_phone(item.phone) or None
        password = item.password.strip()
        if password:
            if len(password) < 4:
                raise HTTPException(status_code=400, detail="Пароль слишком короткий")
            manager.password_hash = hash_password(password)
    save_options(
        db,
        basic_user=payload.basic_user,
        basic_password=payload.basic_password,
        recording_url=payload.recording_url,
        public_url=payload.public_url,
        manager_id=payload.manager_id,
    )
    db.commit()
    if payload.recording_url.strip():
        waiting = list(
            db.scalars(
                select(AtcCall).where(
                    AtcCall.call_id.is_(None), AtcCall.ended_at.is_not(None)
                )
            ).all()
        )
        for row in waiting:
            background.add_task(fetch_and_attach, row.external_id)
    return _settings_out(db)


def _settings_out(db: Session) -> AtcSettingsOut:
    options = load_options(db)
    managers = list(db.scalars(select(Manager).order_by(Manager.name, Manager.id)).all())
    return AtcSettingsOut(
        event_url=options.event_url,
        public_url=options.public_url,
        basic_user=options.basic_user,
        basic_password=options.basic_password,
        recording_url=options.recording_url,
        manager_id=options.manager_id,
        managers=[
            {
                "id": manager.id,
                "name": manager.name,
                "phone": manager.phone or "",
            }
            for manager in managers
        ],
    )


@router.get("/atc/live", response_model=AtcLiveOut)
def live_atc_call(
    db: Session = Depends(get_db),
    manager: Manager = Depends(require_manager),
) -> AtcLiveOut:
    """Current phone call for this employee, so the screen can show recording."""
    row = db.scalar(
        select(AtcCall).where(AtcCall.ended_at.is_(None)).order_by(AtcCall.id.desc())
    )
    if row is None or not sees_atc(row, manager, db):
        return AtcLiveOut(phase="idle")
    return AtcLiveOut(
        phase="recording" if row.recording_on else "starting",
        caller_phone=row.caller_phone,
        external_id=row.external_id,
        recording_on=row.recording_on,
    )


@router.get("/atc/calls/{external_id}", response_model=AtcCallOut)
def get_atc_call(
    external_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_atc),
) -> AtcCall:
    row = db.scalar(select(AtcCall).where(AtcCall.external_id == external_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Звонок АТС не найден")
    return row


@router.post("/atc/calls/{external_id}/recording", response_model=AtcCallOut)
def upload_recording(
    external_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: None = Depends(require_atc),
) -> AtcCall:
    """Attach a file by the PBX CallID. Used until ATC_RECORDING_URL is known."""
    extension = Path(file.filename or "").suffix.lower()
    if extension not in _AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Недопустимое расширение файла")
    payload = file.file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Пустой файл")
    result = store_recording(db, external_id, payload, extension)
    db.commit()
    if result.submit and result.call_id is not None:
        worker.submit_call(result.call_id)
    row = db.scalar(select(AtcCall).where(AtcCall.external_id == external_id.strip()))
    if row is None:
        raise HTTPException(status_code=404, detail="Звонок АТС не найден")
    return row
