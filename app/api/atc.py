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
from app.atc.service import fetch_and_attach, ingest_event, store_recording
from app.config import settings
from app.db.models import AtcCall, AtcCallStatus

router = APIRouter(tags=["atc"])
_basic = HTTPBasic(auto_error=False)
_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}


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
) -> None:
    """Check Basic Auth only after ATC_BASIC_USER and ATC_BASIC_PASSWORD are set."""
    user = settings.ATC_BASIC_USER
    password = settings.ATC_BASIC_PASSWORD
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
    if result.submit and result.call_id is not None:
        worker.submit_call(result.call_id)
    elif result.fetch and result.external_id:
        background.add_task(fetch_and_attach, result.external_id)
    return {}


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
