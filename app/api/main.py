"""FastAPI application: clients, calls, agreements, and manager stats."""

from __future__ import annotations

import shutil
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.agreements_service import mark_overdue
from app.api import worker
from app.api.deps import get_db
from app.api.schemas import (
    AgreementOut,
    AgreementPatch,
    CallDetail,
    CallOut,
    ClientDetail,
    ClientIn,
    ClientOut,
    ManagerIn,
    ManagerOut,
    ManagerStats,
    UtteranceOut,
)
from app.config import settings
from app.db.models import (
    Agreement,
    AgreementResponsible,
    AgreementStatus,
    Call,
    CallStatus,
    Client,
    Manager,
    Utterance,
)
from app.db.session import init_db

ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}
MEDIA_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    worker.requeue_stuck()
    yield
    worker.shutdown_executor()


app = FastAPI(title="MTC", lifespan=lifespan)


def _today() -> date:
    return datetime.now(ZoneInfo(settings.TZ)).date()


def _aware(started_at: datetime) -> datetime:
    if started_at.tzinfo is None:
        return started_at.replace(tzinfo=ZoneInfo(settings.TZ))
    return started_at


def _on_time(agreement: Agreement, tz: ZoneInfo) -> bool:
    """Done with no deadline, or updated on/before the due date in the app timezone."""
    if agreement.due_date is None:
        return True
    updated = agreement.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    return updated.astimezone(tz).date() <= agreement.due_date


def _agreement_sort_key(agreement: Agreement) -> tuple[int, date, int]:
    active = agreement.status in (AgreementStatus.OVERDUE, AgreementStatus.OPEN)
    due = agreement.due_date or date.max
    return (0 if active else 1, due, agreement.id)


def _call_detail(call: Call) -> CallDetail:
    utterances = sorted(call.utterances, key=lambda item: (item.start_sec, item.id))
    agreements = sorted(call.agreements, key=_agreement_sort_key)
    base = CallOut.model_validate(call).model_dump()
    return CallDetail(
        **base,
        utterances=[UtteranceOut.model_validate(item) for item in utterances],
        agreements=[AgreementOut.model_validate(item) for item in agreements],
    )


@app.post("/managers", response_model=ManagerOut)
def create_manager(payload: ManagerIn, db: Session = Depends(get_db)) -> Manager:
    manager = Manager(
        name=payload.name.strip(),
        telegram_chat_id=payload.telegram_chat_id,
        is_supervisor=payload.is_supervisor,
    )
    db.add(manager)
    db.commit()
    db.refresh(manager)
    return manager


@app.get("/managers", response_model=list[ManagerOut])
def list_managers(db: Session = Depends(get_db)) -> list[Manager]:
    return list(db.scalars(select(Manager).order_by(Manager.name, Manager.id)).all())


@app.post("/clients", response_model=ClientOut)
def create_client(payload: ClientIn, db: Session = Depends(get_db)) -> Client:
    name, last_name, phone = _client_names(payload)
    client = Client(name=name, last_name=last_name, phone=phone)
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@app.get("/clients", response_model=list[ClientOut])
def list_clients(
    q: str | None = None,
    sort: str = "name",
    db: Session = Depends(get_db),
) -> list[Client]:
    if sort not in {"name", "last_name", "call"}:
        raise HTTPException(status_code=400, detail="Неизвестная сортировка")
    clients = list(db.scalars(select(Client)).all())
    needle = (q or "").strip().casefold()
    if needle:
        clients = [
            client
            for client in clients
            if needle
            in " ".join(
                part for part in (client.name, client.last_name, client.phone) if part
            ).casefold()
        ]
    return _sort_clients(clients, sort, db)


def _sort_clients(clients: list[Client], sort: str, db: Session) -> list[Client]:
    if sort == "call":
        latest = dict(
            db.execute(
                select(Call.client_id, func.max(Call.started_at)).group_by(Call.client_id)
            ).all()
        )
        missing = datetime.min.replace(tzinfo=UTC)
        return sorted(clients, key=lambda client: latest.get(client.id) or missing, reverse=True)
    if sort == "last_name":
        return sorted(
            clients,
            key=lambda client: (client.last_name.casefold(), client.name.casefold(), client.id),
        )
    return sorted(
        clients,
        key=lambda client: (client.name.casefold(), client.last_name.casefold(), client.id),
    )


def _client_names(payload: ClientIn) -> tuple[str, str, str]:
    name = payload.name.strip()
    last_name = payload.last_name.strip()
    phone = payload.phone.strip()
    if not name or not last_name or not phone:
        raise HTTPException(status_code=400, detail="Нужны имя, фамилия и номер")
    return name, last_name, phone


def _forget_saved(audio_path: str, call_id: int) -> None:
    path = Path(audio_path)
    if path.is_file():
        path.unlink()
    processed = settings.DATA_DIR / "processed" / str(call_id)
    if processed.is_dir():
        shutil.rmtree(processed, ignore_errors=True)


def _remove_call(db: Session, call: Call) -> None:
    db.execute(delete(Utterance).where(Utterance.call_id == call.id))
    db.execute(delete(Agreement).where(Agreement.call_id == call.id))
    db.delete(call)


@app.patch("/clients/{client_id}", response_model=ClientOut)
def update_client(client_id: int, payload: ClientIn, db: Session = Depends(get_db)) -> Client:
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    name, last_name, phone = _client_names(payload)
    client.name = name
    client.last_name = last_name
    client.phone = phone
    db.commit()
    db.refresh(client)
    return client


@app.delete("/clients/{client_id}", status_code=204)
def delete_client(client_id: int, db: Session = Depends(get_db)) -> Response:
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    calls = list(client.calls)
    saved = [(call.audio_path, call.id) for call in calls]
    for call in calls:
        _remove_call(db, call)
    db.delete(client)
    db.commit()
    for audio_path, call_id in saved:
        _forget_saved(audio_path, call_id)
    return Response(status_code=204)


@app.get("/clients/{client_id}", response_model=ClientDetail)
def get_client(client_id: int, db: Session = Depends(get_db)) -> ClientDetail:
    mark_overdue(db, _today())
    client = db.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    calls = list(
        db.scalars(
            select(Call)
            .where(Call.client_id == client_id)
            .order_by(Call.started_at.desc(), Call.id.desc())
        ).all()
    )
    agreements = sorted(client.agreements, key=_agreement_sort_key)
    base = ClientOut.model_validate(client).model_dump()
    return ClientDetail(
        **base,
        calls=[CallOut.model_validate(item) for item in calls],
        agreements=[AgreementOut.model_validate(item) for item in agreements],
    )


@app.post("/calls", response_model=CallOut)
def create_call(
    file: UploadFile = File(...),
    client_id: int = Form(...),
    manager_id: int = Form(...),
    started_at: datetime | None = Form(default=None),
    db: Session = Depends(get_db),
) -> Call:
    if db.get(Client, client_id) is None:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    if db.get(Manager, manager_id) is None:
        raise HTTPException(status_code=404, detail="Менеджер не найден")

    original = Path(file.filename or "").name
    ext = Path(original).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Недопустимое расширение файла")

    payload = file.file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Пустой файл")

    when = _aware(started_at) if started_at is not None else datetime.now(ZoneInfo(settings.TZ))
    call = Call(
        client_id=client_id,
        manager_id=manager_id,
        audio_path="pending",
        started_at=when,
        duration_sec=0,
        channels=0,
        status=CallStatus.NEW,
    )
    db.add(call)
    db.flush()

    raw_dir = settings.DATA_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / f"{call.id}_{original}"
    try:
        dest.write_bytes(payload)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    call.audio_path = str(dest)
    db.commit()
    db.refresh(call)
    worker.submit_call(call.id)
    return call


@app.get("/calls", response_model=list[CallOut])
def list_calls(
    client_id: int | None = None,
    manager_id: int | None = None,
    status: CallStatus | None = None,
    db: Session = Depends(get_db),
) -> list[Call]:
    stmt = select(Call).order_by(Call.started_at.desc(), Call.id.desc())
    if client_id is not None:
        stmt = stmt.where(Call.client_id == client_id)
    if manager_id is not None:
        stmt = stmt.where(Call.manager_id == manager_id)
    if status is not None:
        stmt = stmt.where(Call.status == status)
    return list(db.scalars(stmt).all())


@app.get("/calls/{call_id}", response_model=CallDetail)
def get_call(call_id: int, db: Session = Depends(get_db)) -> CallDetail:
    call = db.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Звонок не найден")
    return _call_detail(call)


@app.post("/calls/{call_id}/reprocess", response_model=CallOut)
def reprocess_call(call_id: int, db: Session = Depends(get_db)) -> Call:
    call = db.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Звонок не найден")
    call.status = CallStatus.NEW
    call.error_message = None
    db.commit()
    db.refresh(call)
    worker.submit_call(call.id)
    return call


@app.delete("/calls/{call_id}", status_code=204)
def delete_call(call_id: int, db: Session = Depends(get_db)) -> Response:
    call = db.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Звонок не найден")
    saved = (call.audio_path, call.id)
    _remove_call(db, call)
    db.commit()
    _forget_saved(*saved)
    return Response(status_code=204)


@app.get("/calls/{call_id}/audio")
def get_call_audio(call_id: int, db: Session = Depends(get_db)) -> FileResponse:
    call = db.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Звонок не найден")
    path = Path(call.audio_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Аудиофайл не найден")
    media = MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media, filename=path.name)


@app.get("/agreements", response_model=list[AgreementOut])
def list_agreements(
    status: AgreementStatus | None = None,
    responsible: AgreementResponsible | None = None,
    manager_id: int | None = None,
    client_id: int | None = None,
    due_before: date | None = None,
    db: Session = Depends(get_db),
) -> list[Agreement]:
    mark_overdue(db, _today())
    stmt = select(Agreement).join(Call, Agreement.call_id == Call.id)
    if status is not None:
        stmt = stmt.where(Agreement.status == status)
    if responsible is not None:
        stmt = stmt.where(Agreement.responsible == responsible)
    if manager_id is not None:
        stmt = stmt.where(Call.manager_id == manager_id)
    if client_id is not None:
        stmt = stmt.where(Agreement.client_id == client_id)
    if due_before is not None:
        stmt = stmt.where(Agreement.due_date.is_not(None), Agreement.due_date <= due_before)
    rows = list(db.scalars(stmt).all())
    return sorted(rows, key=_agreement_sort_key)


@app.patch("/agreements/{agreement_id}", response_model=AgreementOut)
def patch_agreement(
    agreement_id: int,
    payload: AgreementPatch,
    db: Session = Depends(get_db),
) -> Agreement:
    agreement = db.get(Agreement, agreement_id)
    if agreement is None:
        raise HTTPException(status_code=404, detail="Договорённость не найдена")
    data = payload.model_dump(exclude_unset=True)
    if "action" in data and not str(data["action"]).strip():
        raise HTTPException(status_code=400, detail="Действие не может быть пустым")
    for key, value in data.items():
        setattr(agreement, key, value)
    agreement.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(agreement)
    return agreement


@app.get("/stats/managers", response_model=list[ManagerStats])
def manager_stats(db: Session = Depends(get_db)) -> list[ManagerStats]:
    """Per manager: open, overdue, done, and percent of done agreements closed on time."""
    mark_overdue(db, _today())
    tz = ZoneInfo(settings.TZ)
    managers = list(db.scalars(select(Manager).order_by(Manager.name, Manager.id)).all())
    stats: list[ManagerStats] = []
    for manager in managers:
        agreements = list(
            db.scalars(
                select(Agreement)
                .join(Call, Agreement.call_id == Call.id)
                .where(Call.manager_id == manager.id)
            ).all()
        )
        open_count = sum(1 for item in agreements if item.status == AgreementStatus.OPEN)
        overdue_count = sum(1 for item in agreements if item.status == AgreementStatus.OVERDUE)
        done = [item for item in agreements if item.status == AgreementStatus.DONE]
        if done:
            on_time = sum(1 for item in done if _on_time(item, tz))
            percent: float | None = round(on_time / len(done) * 100, 1)
        else:
            percent = None
        stats.append(
            ManagerStats(
                manager_id=manager.id,
                name=manager.name,
                open=open_count,
                overdue=overdue_count,
                done=len(done),
                done_on_time=percent,
            )
        )
    return stats
