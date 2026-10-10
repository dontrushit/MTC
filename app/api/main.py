"""FastAPI application: clients, calls, agreements, and manager stats."""

from __future__ import annotations

import json
import shutil
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import secure
from app.agreements_service import mark_overdue
from app.api import worker
from app.api.atc import router as atc_router
from app.api.auth import router as auth_router
from app.api.deps import get_db
from app.api.guard import require_login, require_manager, require_supervisor
from app.api.schemas import (
    AgreementIn,
    AgreementOut,
    AgreementPatch,
    AuditOut,
    CallDetail,
    CallOut,
    ClientDetail,
    ClientIn,
    ClientOut,
    ConsentIn,
    CrmSendOut,
    CrmSettingsIn,
    CrmSettingsOut,
    HistoryOut,
    ManagerIn,
    ManagerOut,
    ManagerStats,
    ReportPatch,
    RulesIn,
    RulesOut,
    UtteranceOut,
)
from app.atc.access import sees_atc
from app.atc.phones import normalize_phone
from app.atc.service import find_client
from app.audit import action_ru
from app.audit import as_dict as audit_dict
from app.audit import log as audit_log
from app.audit import recent as audit_recent
from app.auth import hash_password
from app.by_phone import normalize_by_phone
from app.config import settings
from app.db.models import (
    Agreement,
    AgreementResponsible,
    AgreementStatus,
    AtcCall,
    Call,
    CallStatus,
    Client,
    Manager,
    Utterance,
)
from app.db.session import init_db
from app.extraction.dates import resolve_due
from app.integrations.crm import payload_for, send_to_crm
from app.integrations.ics import build_ics
from app.rules import CATEGORIES, PRIORITIES, classify, load_rules, rules_from_payload
from app.secure import unlock_to

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


app = FastAPI(title="MTC", lifespan=lifespan, dependencies=[Depends(require_login)])
app.include_router(auth_router)
app.include_router(atc_router)


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
def create_manager(
    payload: ManagerIn,
    db: Session = Depends(get_db),
    _: Manager = Depends(require_supervisor),
) -> Manager:
    password = (payload.password or "").strip()
    if password and len(password) < 4:
        raise HTTPException(status_code=400, detail="Пароль слишком короткий")
    manager = Manager(
        name=payload.name.strip(),
        phone=normalize_phone(payload.phone) or None,
        password_hash=hash_password(password) if password else None,
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
    name, last_name, phone, contract_number = _client_names(payload)
    client = Client(
        name=name,
        last_name=last_name,
        phone=phone,
        contract_number=contract_number,
    )
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
                part
                for part in (
                    client.name,
                    client.last_name,
                    client.phone,
                    client.contract_number,
                )
                if part
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


def _client_names(payload: ClientIn) -> tuple[str, str, str, str]:
    name = payload.name.strip()
    last_name = payload.last_name.strip()
    phone = normalize_by_phone(payload.phone)
    contract_number = payload.contract_number.strip()
    if not name or not last_name or not phone:
        raise HTTPException(
            status_code=400,
            detail="Нужны имя, фамилия и номер: +375, код из 2 цифр и ещё 7",
        )
    return name, last_name, phone, contract_number


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
    name, last_name, phone, contract_number = _client_names(payload)
    client.name = name
    client.last_name = last_name
    client.phone = phone
    client.contract_number = contract_number
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
    consent: bool = Form(default=False),
    db: Session = Depends(get_db),
    manager: Manager = Depends(require_manager),
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
        consent=consent,
    )
    db.add(call)
    db.flush()
    audit_log(
        db,
        manager=manager,
        action="consent" if consent else "upload_call",
        entity="call",
        entity_id=call.id,
        detail="клиент предупреждён о записи" if consent else "загрузка записи",
    )

    raw_dir = settings.DATA_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / f"{call.id}_{original}"
    try:
        dest.write_bytes(payload)
        secure.lock(dest)
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


@app.get("/history", response_model=list[HistoryOut])
def call_history(
    limit: int = 40,
    db: Session = Depends(get_db),
    manager: Manager = Depends(require_manager),
) -> list[HistoryOut]:
    """This employee's latest calls, including a PBX call that has no report yet."""
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="Слишком длинный список")
    items = [_history_call(call) for call in _recent_calls(db, limit, manager.id)]
    pending = [row for row in _pending_atc(db, limit) if sees_atc(row, manager, db)]
    items.extend(_history_atc(row, db) for row in pending)
    items.sort(key=_history_order)
    return items[:limit]


def _recent_calls(db: Session, limit: int, manager_id: int) -> list[Call]:
    return list(
        db.scalars(
            select(Call)
            .where(Call.manager_id == manager_id)
            .order_by(Call.started_at.desc(), Call.id.desc())
            .limit(limit)
        ).all()
    )


def _pending_atc(db: Session, limit: int) -> list[AtcCall]:
    return list(
        db.scalars(
            select(AtcCall)
            .where(AtcCall.call_id.is_(None))
            .order_by(AtcCall.id.desc())
            .limit(limit)
        ).all()
    )


def _history_call(call: Call) -> HistoryOut:
    client = call.client
    name = " ".join(part for part in (client.name, client.last_name) if part).strip()
    if call.status == CallStatus.ERROR:
        status = "error"
    elif call.status == CallStatus.EXTRACTED:
        status = "ready"
    else:
        status = "preparing"
    return HistoryOut(
        call_id=call.id,
        client_id=client.id,
        started_at=call.started_at,
        client_name=name,
        phone=client.phone,
        status=status,
        topic=call.report_topic or "",
        error_message=call.error_message,
    )


def _history_atc(row: AtcCall, db: Session) -> HistoryOut:
    client = find_client(db, row.caller_phone)
    if client is None:
        name = ""
        phone = row.caller_phone
        client_id = None
    else:
        name = " ".join(part for part in (client.name, client.last_name) if part).strip()
        phone = client.phone
        client_id = client.id
    if row.ended_at is None:
        status = "recording" if row.recording_on else "starting"
    else:
        status = "waiting_recording"
    return HistoryOut(
        call_id=None,
        client_id=client_id,
        started_at=row.started_at,
        client_name=name,
        phone=phone,
        status=status,
        topic="",
        error_message=row.note or None,
    )


def _history_order(item: HistoryOut) -> tuple[int, float, int]:
    ongoing = item.status in {"starting", "recording"}
    stamp = item.started_at or datetime.min.replace(tzinfo=UTC)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return (0 if ongoing else 1, -stamp.timestamp(), -(item.call_id or 0))


@app.get("/calls/{call_id}", response_model=CallDetail)
def get_call(
    call_id: int,
    db: Session = Depends(get_db),
    manager: Manager = Depends(require_manager),
) -> CallDetail:
    call = db.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Звонок не найден")
    audit_log(db, manager=manager, action="open_call", entity="call", entity_id=call.id)
    db.commit()
    db.refresh(call)
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
def get_call_audio(
    call_id: int,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    manager: Manager = Depends(require_manager),
) -> FileResponse:
    call = db.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Звонок не найден")
    path = Path(call.audio_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Аудиофайл не найден")
    audit_log(
        db,
        manager=manager,
        action="listen_audio",
        entity="call",
        entity_id=call.id,
        detail=path.name,
    )
    db.commit()
    media = MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    if secure.is_encrypted(path):
        temp_file = unlock_to(path, settings.DATA_DIR / "tmp" / path.name)
        background.add_task(_drop_file, temp_file)
        return FileResponse(temp_file, media_type=media, filename=path.name)
    return FileResponse(path, media_type=media, filename=path.name)


def _drop_file(path: Path) -> None:
    path.unlink(missing_ok=True)


@app.patch("/calls/{call_id}/consent", response_model=CallOut)
def patch_consent(
    call_id: int,
    payload: ConsentIn,
    db: Session = Depends(get_db),
    manager: Manager = Depends(require_manager),
) -> Call:
    """Mark that the client was told the call was recorded."""
    call = db.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Звонок не найден")
    call.consent = payload.consent
    audit_log(
        db,
        manager=manager,
        action="consent",
        entity="call",
        entity_id=call.id,
        detail="клиент предупреждён о записи" if payload.consent else "снято",
    )
    db.commit()
    db.refresh(call)
    return call


@app.get("/calls/{call_id}/calendar.ics")
def agreement_calendar(
    call_id: int,
    db: Session = Depends(get_db),
    manager: Manager = Depends(require_manager),
) -> Response:
    call = db.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Звонок не найден")
    parts = [
        build_ics_for(db, agreement, manager=manager)
        for agreement in sorted(call.agreements, key=_agreement_sort_key)
    ]
    if not parts:
        parts = [
            build_ics(
                agreement_id=0,
                action=call.report_topic or "Звонок",
                client_name=call.client.name,
                responsible="",
                due_date=call.started_at.astimezone(ZoneInfo(settings.TZ)).date(),
                due_text="",
                amount=None,
                conditions=None,
                quote="",
                fallback=call.started_at,
            )
        ]
    body = "".join(parts)
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="call_{call_id}.ics"',
        },
    )


def build_ics_for(
    db: Session,
    agreement: Agreement,
    *,
    manager: Manager,
) -> str:
    client = db.get(Client, agreement.client_id)
    audit_log(
        db,
        manager=manager,
        action="download_ics",
        entity="agreement",
        entity_id=agreement.id,
        detail=agreement.action,
    )
    fallback = agreement.created_at if agreement.created_at.tzinfo else datetime.now(UTC)
    return build_ics(
        agreement_id=agreement.id,
        action=agreement.action,
        client_name=(
            " ".join(part for part in (client.name, client.last_name) if part)
            if client is not None
            else ""
        ),
        responsible=agreement.responsible,
        due_date=agreement.due_date,
        due_text=agreement.due_text,
        amount=agreement.amount,
        conditions=agreement.conditions,
        quote=agreement.quote,
        fallback=fallback,
    )


@app.get("/agreements/{agreement_id}/calendar.ics")
def agreement_ics(
    agreement_id: int,
    db: Session = Depends(get_db),
    manager: Manager = Depends(require_manager),
) -> Response:
    agreement = db.get(Agreement, agreement_id)
    if agreement is None:
        raise HTTPException(status_code=404, detail="Договорённость не найдена")
    body = build_ics_for(db, agreement, manager=manager)
    db.commit()
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="agreement_{agreement_id}.ics"',
        },
    )


@app.post("/agreements/{agreement_id}/send-to-crm", response_model=CrmSendOut)
def agreement_to_crm(
    agreement_id: int,
    db: Session = Depends(get_db),
    manager: Manager = Depends(require_manager),
) -> CrmSendOut:
    agreement = db.get(Agreement, agreement_id)
    if agreement is None:
        raise HTTPException(status_code=404, detail="Договорённость не найдена")
    url, token = _crm_options(db)
    if not url.strip():
        raise HTTPException(
            status_code=409,
            detail="Сначала введите ссылку CRM на экране «Настройка АТС»",
        )
    client = db.get(Client, agreement.client_id)
    data = AgreementOut.model_validate(agreement).model_dump(mode="json")
    sent, message = send_to_crm(
        url.strip(),
        payload_for(
            data,
            client_name=(
                " ".join(part for part in (client.name, client.last_name) if part)
                if client is not None
                else ""
            ),
            phone=client.phone if client is not None else "",
        ),
        token=token.strip(),
    )
    audit_log(
        db,
        manager=manager,
        action="send_crm",
        entity="agreement",
        entity_id=agreement.id,
        detail=message,
    )
    db.commit()
    return CrmSendOut(sent=sent, message=message)


def _crm_options(db: Session) -> tuple[str, str]:
    from app.db.models import AppSetting

    stored = {row.key: row.value for row in db.scalars(select(AppSetting)).all()}
    return stored.get("crm_webhook_url", ""), stored.get("crm_token", "")


@app.get("/crm/settings", response_model=CrmSettingsOut)
def get_crm_settings(
    db: Session = Depends(get_db),
    _: Manager = Depends(require_supervisor),
) -> CrmSettingsOut:
    url, token = _crm_options(db)
    return CrmSettingsOut(webhook_url=url, token=token)


@app.put("/crm/settings", response_model=CrmSettingsOut)
def update_crm_settings(
    payload: CrmSettingsIn,
    db: Session = Depends(get_db),
    _: Manager = Depends(require_supervisor),
) -> CrmSettingsOut:
    from app.db.models import AppSetting

    def write(key: str, value: str) -> None:
        row = db.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key, value=value)
            db.add(row)
        row.value = value

    write("crm_webhook_url", payload.webhook_url.strip())
    write("crm_token", payload.token.strip())
    db.commit()
    url, token = _crm_options(db)
    return CrmSettingsOut(webhook_url=url, token=token)


@app.get("/agreement-rules", response_model=RulesOut)
def get_rules(
    db: Session = Depends(get_db),
    _: Manager = Depends(require_supervisor),
) -> RulesOut:
    return RulesOut(
        rules=load_rules(db),
        categories=list(CATEGORIES),
        priorities=list(PRIORITIES),
    )


@app.put("/agreement-rules", response_model=RulesOut)
def update_rules(
    payload: RulesIn,
    db: Session = Depends(get_db),
    _: Manager = Depends(require_supervisor),
) -> RulesOut:
    try:
        rules_from_payload(db, payload.rules)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return RulesOut(
        rules=load_rules(db),
        categories=list(CATEGORIES),
        priorities=list(PRIORITIES),
    )


@app.get("/audit", response_model=list[AuditOut])
def list_audit(
    limit: int = 100,
    db: Session = Depends(get_db),
    _: Manager = Depends(require_supervisor),
) -> list[AuditOut]:
    rows = audit_recent(db, limit=min(max(limit, 1), 500))
    return [
        AuditOut(**audit_dict(row), action_ru=action_ru(row.action))
        for row in rows
    ]


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


@app.patch("/calls/{call_id}/report", response_model=CallOut)
def update_call_report(
    call_id: int,
    payload: ReportPatch,
    db: Session = Depends(get_db),
) -> Call:
    call = db.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Звонок не найден")
    topic = payload.topic.strip()
    brief = payload.brief.strip()
    unresolved = payload.unresolved.strip()
    call.report_topic = topic
    call.report_summary = brief
    call.report_json = json.dumps(
        {"topic": topic, "brief": brief, "unresolved": unresolved},
        ensure_ascii=False,
    )
    db.commit()
    db.refresh(call)
    return call


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


@app.post("/calls/{call_id}/agreements", response_model=AgreementOut)
def create_agreement(
    call_id: int,
    payload: AgreementIn,
    db: Session = Depends(get_db),
    manager: Manager = Depends(require_manager),
) -> Agreement:
    call = db.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Звонок не найден")
    due_text = payload.due_text.strip()
    due_date = payload.due_date
    if due_date is not None and not due_text:
        due_text = due_date.isoformat()
    if due_date is None and due_text:
        due_date = resolve_due(due_text, call.started_at, ZoneInfo(settings.TZ))
    category, priority = _classify_new(payload, db)
    agreement = Agreement(
        call_id=call.id,
        client_id=call.client_id,
        action=payload.action.strip(),
        responsible=payload.responsible,
        due_date=due_date,
        due_text=due_text,
        amount=_blank_to_none(payload.amount),
        conditions=_blank_to_none(payload.conditions),
        quote=payload.quote.strip(),
        category=category,
        priority=priority,
    )
    db.add(agreement)
    db.flush()
    audit_log(
        db,
        manager=manager,
        action="create_agreement",
        entity="agreement",
        entity_id=agreement.id,
        detail=agreement.action,
    )
    db.commit()
    db.refresh(agreement)
    return agreement


def _classify_new(payload: AgreementIn, db: Session) -> tuple[str, str]:
    rules = load_rules(db)
    category = payload.category if payload.category is not None else ""
    priority = payload.priority if payload.priority is not None else ""
    if not category or not priority:
        guessed_category, guessed_priority = classify(payload.action, rules)
        category = category or guessed_category
        priority = priority or guessed_priority
    if category not in CATEGORIES:
        category = ""
    if priority not in PRIORITIES:
        priority = "normal"
    return category, priority


@app.patch("/agreements/{agreement_id}", response_model=AgreementOut)
def patch_agreement(
    agreement_id: int,
    payload: AgreementPatch,
    db: Session = Depends(get_db),
    manager: Manager = Depends(require_manager),
) -> Agreement:
    agreement = db.get(Agreement, agreement_id)
    if agreement is None:
        raise HTTPException(status_code=404, detail="Договорённость не найдена")
    data = payload.model_dump(exclude_unset=True)
    if "action" in data:
        data["action"] = str(data["action"]).strip()
        if not data["action"]:
            raise HTTPException(status_code=400, detail="Действие не может быть пустым")
    if "amount" in data:
        data["amount"] = _blank_to_none(data["amount"])
    if "conditions" in data:
        data["conditions"] = _blank_to_none(data["conditions"])
    if "quote" in data and data["quote"] is not None:
        data["quote"] = data["quote"].strip()
    if "due_text" in data and data["due_text"] is not None:
        data["due_text"] = data["due_text"].strip()
    if data.get("due_date") is not None and not data.get("due_text"):
        data["due_text"] = data["due_date"].isoformat()
    if data.get("due_text") and "due_date" not in data:
        call = db.get(Call, agreement.call_id)
        if call is not None:
            data["due_date"] = resolve_due(
                data["due_text"], call.started_at, ZoneInfo(settings.TZ)
            )
    action_changed = data.get("action") and data["action"] != agreement.action
    if "category" not in data and "priority" not in data and action_changed:
        guessed_category, guessed_priority = classify(data["action"], load_rules(db))
        data["category"] = guessed_category or agreement.category
        data["priority"] = guessed_priority
    if "priority" in data and data["priority"] not in PRIORITIES:
        data["priority"] = "normal"
    for key, value in data.items():
        setattr(agreement, key, value)
    agreement.updated_at = datetime.now(UTC)
    audit_log(
        db,
        manager=manager,
        action="edit_agreement",
        entity="agreement",
        entity_id=agreement.id,
        detail=", ".join(sorted(data)) or "правка",
    )
    db.commit()
    db.refresh(agreement)
    return agreement


@app.delete("/agreements/{agreement_id}", status_code=204)
def delete_agreement(
    agreement_id: int,
    db: Session = Depends(get_db),
    manager: Manager = Depends(require_manager),
) -> Response:
    agreement = db.get(Agreement, agreement_id)
    if agreement is None:
        raise HTTPException(status_code=404, detail="Договорённость не найдена")
    detail = agreement.action
    audit_log(
        db,
        manager=manager,
        action="delete_agreement",
        entity="agreement",
        entity_id=agreement.id,
        detail=detail,
    )
    db.delete(agreement)
    db.commit()
    return Response(status_code=204)


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
