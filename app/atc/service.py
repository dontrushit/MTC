"""Map Автосекретарь events onto a client, a manager, and the existing pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import worker
from app.atc import recording
from app.atc.phones import normalize_phone
from app.config import settings
from app.db.models import AtcCall, AtcCallStatus, Call, CallStatus, Client, Manager
from app.db.session import get_session

logger = logging.getLogger(__name__)

TRANSFER = 9
SHORT_TRANSFER = 11
REC_STOP = 14
END_CALL = 15
STATISTICS = 26
TRANSFER_OK = "1280"
FINISHED_EVENTS = {REC_STOP, END_CALL, STATISTICS}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}
UNKNOWN_CLIENT = "Неизвестный"


@dataclass
class IngestResult:
    external_id: str = ""
    call_id: int | None = None
    submit: bool = False
    fetch: bool = False


def ingest_event(session: Session, payload: dict) -> IngestResult:
    """Store one PBX event and queue the call when the recording is already here."""
    external_id = str(payload.get("CallID") or "").strip()
    if not external_id:
        return IngestResult()

    event_type = _as_int(payload.get("EventType"))
    row = _get_or_create(session, external_id)
    if event_type is not None:
        row.last_event = event_type

    when = _parse_time(payload.get("EventTime"))
    if row.started_at is None:
        row.started_at = when or _now()
    caller = normalize_phone(_text(payload.get("AN")))
    if caller:
        row.caller_phone = caller
    if _carries_agent(event_type, payload):
        agent = normalize_phone(_text(payload.get("DN1")) or _text(payload.get("EXT1")))
        if agent:
            row.agent_phone = agent
    duration = _as_int(payload.get("Duration"))
    if duration is None:
        duration = _as_int(payload.get("Recdur"))
    if duration is not None:
        row.duration_sec = duration
        _fill_call_duration(session, row, duration)
    if event_type in FINISHED_EVENTS and row.ended_at is None:
        row.ended_at = when or _now()

    result = IngestResult(external_id=external_id)
    if row.ended_at is not None and row.call_id is None:
        call_id, submit = queue_recording(session, row)
        result.call_id = call_id
        result.submit = submit
        result.fetch = (
            call_id is None
            and not _recording_ready(row)
            and bool(settings.ATC_RECORDING_URL.strip())
        )
    elif row.call_id is not None:
        result.call_id = row.call_id
    session.flush()
    return result


def store_recording(
    session: Session,
    external_id: str,
    payload: bytes,
    extension: str,
) -> IngestResult:
    """Save an uploaded recording and queue it if the call has already ended."""
    row = _get_or_create(session, external_id.strip())
    _write_recording(row, payload, extension)
    call_id, submit = queue_recording(session, row)
    session.flush()
    return IngestResult(
        external_id=row.external_id,
        call_id=call_id,
        submit=submit,
    )


def fetch_and_attach(external_id: str) -> None:
    """Download the recording after the HTTP handler has already answered MTS."""
    payload = recording.fetch_recording(external_id)
    if not payload:
        return
    call_id: int | None = None
    with get_session() as session:
        row = session.scalar(select(AtcCall).where(AtcCall.external_id == external_id))
        if row is None or row.call_id is not None:
            return
        _write_recording(row, payload, suffix_for(payload))
        call_id, submit = queue_recording(session, row)
        if not submit:
            call_id = None
    if call_id is not None:
        worker.submit_call(call_id)


def queue_recording(session: Session, row: AtcCall) -> tuple[int | None, bool]:
    """Create the pipeline call once. The caller commits, then submits the worker."""
    if row.call_id is not None:
        return row.call_id, False
    if row.ended_at is None or not _recording_ready(row):
        if row.ended_at is not None:
            row.status = AtcCallStatus.WAITING_RECORDING
            if not settings.ATC_RECORDING_URL.strip():
                row.note = (
                    "Нет файла записи. Когда МТС даст ссылку, "
                    "её достаточно вписать в ATC_RECORDING_URL."
                )
        return None, False
    if not row.caller_phone:
        row.status = AtcCallStatus.WAITING_RECORDING
        row.note = "В событии не было номера звонящего."
        return None, False

    manager = resolve_manager(session, row.agent_phone)
    if manager is None:
        row.status = AtcCallStatus.WAITING_RECORDING
        row.note = "Нет менеджера. Добавьте менеджера или укажите ATC_MANAGER_ID."
        return None, False

    client = find_client(session, row.caller_phone)
    if client is None:
        client = Client(name=UNKNOWN_CLIENT, last_name="", phone=row.caller_phone)
        session.add(client)
        session.flush()

    call = Call(
        client_id=client.id,
        manager_id=manager.id,
        audio_path="pending",
        started_at=row.started_at or _now(),
        duration_sec=row.duration_sec or 0,
        channels=0,
        status=CallStatus.NEW,
    )
    session.add(call)
    session.flush()
    call.audio_path = str(_copy_into_raw(row, call.id))
    row.call_id = call.id
    row.status = AtcCallStatus.QUEUED
    row.note = ""
    return call.id, True


def find_client(session: Session, phone: str) -> Client | None:
    target = normalize_phone(phone)
    if not target:
        return None
    clients = session.scalars(select(Client).order_by(Client.id)).all()
    for client in clients:
        if normalize_phone(client.phone) == target:
            return client
    return None


def resolve_manager(session: Session, agent_phone: str) -> Manager | None:
    managers = list(session.scalars(select(Manager).order_by(Manager.id)).all())
    if not managers:
        return None
    target = normalize_phone(agent_phone)
    if target:
        for manager in managers:
            if normalize_phone(manager.phone) == target:
                return manager
    configured = _configured_manager_id()
    if configured is not None:
        for manager in managers:
            if manager.id == configured:
                return manager
    return managers[0]


def suffix_for(payload: bytes) -> str:
    if payload.startswith(b"RIFF"):
        return ".wav"
    if payload.startswith(b"ID3") or payload[:2] == b"\xff\xfb":
        return ".mp3"
    if payload.startswith(b"OggS"):
        return ".ogg"
    if payload.startswith(b"fLaC"):
        return ".flac"
    if b"ftyp" in payload[:32]:
        return ".m4a"
    return ".wav"


def _get_or_create(session: Session, external_id: str) -> AtcCall:
    row = session.scalar(select(AtcCall).where(AtcCall.external_id == external_id))
    if row is not None:
        return row
    row = AtcCall(external_id=external_id, status=AtcCallStatus.OPEN)
    session.add(row)
    session.flush()
    return row


def _write_recording(row: AtcCall, payload: bytes, extension: str) -> None:
    ext = extension if extension in AUDIO_EXTENSIONS else ".wav"
    folder = settings.DATA_DIR / "atc"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{_safe_id(row.external_id)}{ext}"
    dest.write_bytes(payload)
    row.recording_path = str(dest)


def _copy_into_raw(row: AtcCall, call_id: int) -> Path:
    source = Path(row.recording_path)
    ext = source.suffix.lower() if source.suffix.lower() in AUDIO_EXTENSIONS else ".wav"
    folder = settings.DATA_DIR / "raw"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{call_id}_atc{ext}"
    dest.write_bytes(source.read_bytes())
    return dest


def _recording_ready(row: AtcCall) -> bool:
    if not row.recording_path:
        return False
    path = Path(row.recording_path)
    return path.is_file() and path.stat().st_size > 0


def _fill_call_duration(session: Session, row: AtcCall, duration: int) -> None:
    if row.call_id is None:
        return
    call = session.get(Call, row.call_id)
    if call is not None and call.duration_sec == 0:
        call.duration_sec = duration


def _carries_agent(event_type: int | None, payload: dict) -> bool:
    if event_type == TRANSFER:
        return str(payload.get("Result") or "") == TRANSFER_OK
    if event_type == SHORT_TRANSFER:
        return bool(payload.get("DN1") or payload.get("EXT1"))
    return False


def _configured_manager_id() -> int | None:
    raw = str(settings.ATC_MANAGER_ID or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning("ATC_MANAGER_ID is not a number")
        return None


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=ZoneInfo(settings.TZ))
    return parsed


def _now() -> datetime:
    return datetime.now(ZoneInfo(settings.TZ))


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None or isinstance(value, str) and not value.strip():
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_id(external_id: str) -> str:
    cleaned = "".join(ch for ch in external_id if ch.isalnum() or ch in "-_")
    return cleaned or "call"
