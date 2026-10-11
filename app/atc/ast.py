"""Harmonize ASTService (Asterisk + Linphone) recordings with the MTC pipeline.

The PBX service posts one multipart webhook after every finished call:
`metadata` (JSON string) plus audio files `mixed`, `caller_mono`,
`callee_mono` and, when merging is on, `stereo` (L=caller, R=callee).
The caller extension is the employee, the callee is the client side.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import secure
from app.atc.phones import normalize_phone
from app.atc.service import find_client, resolve_manager, suffix_for
from app.config import settings
from app.db.models import AtcCall, AtcCallStatus, Call, CallStatus, Client

UNKNOWN_CLIENT = "Неизвестный контакт"
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}


@dataclass
class AstResult:
    external_id: str = ""
    call_id: int | None = None
    submit: bool = False
    note: str = ""


def parse_metadata(raw: str | None) -> dict:
    if not raw or not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def pick_audio(files: dict[str, bytes | None]) -> tuple[str, bytes]:
    """Stereo is the best: the pipeline splits it by channels. Mono is diarized."""
    for name in ("stereo", "mixed", "caller_mono", "callee_mono"):
        payload = files.get(name)
        if payload:
            return name, payload
    return "", b""


def ingest_ast_call(
    session: Session,
    meta: dict,
    audio_name: str,
    audio: bytes,
    extension: str,
) -> AstResult:
    """One finished Linphone call → client, manager, encrypted file, pipeline."""
    external_id = str(meta.get("call_id") or "").strip()
    if not external_id or not audio:
        return AstResult(external_id=external_id, note="нет call_id или файла записи")

    row = session.scalar(select(AtcCall).where(AtcCall.external_id == external_id))
    if row is not None and row.call_id is not None:
        return AstResult(external_id=external_id, call_id=row.call_id, note="уже в очереди")
    if row is None:
        row = AtcCall(external_id=external_id, status=AtcCallStatus.OPEN)
        session.add(row)
        session.flush()

    caller = normalize_phone(meta.get("caller"))
    callee = normalize_phone(meta.get("callee")) or caller
    answered = _as_int(meta.get("answered_seconds"))
    finished_at = _parse_time(meta.get("finished_at"))
    started_at = finished_at - timedelta(seconds=answered) if finished_at else _now()

    row.caller_phone = callee
    row.agent_phone = caller
    row.started_at = started_at
    row.ended_at = finished_at or _now()
    row.duration_sec = answered or 0
    row.recording_on = True

    manager = resolve_manager(session, caller)
    if manager is None:
        row.status = AtcCallStatus.WAITING_RECORDING
        row.note = "Нет сотрудника. Добавьте его на экране «Телефония»."
        session.flush()
        return AstResult(external_id=external_id, note=row.note)

    client = find_client(session, callee)
    if client is None:
        client = Client(name=UNKNOWN_CLIENT, last_name="", phone=callee)
        session.add(client)
        session.flush()

    dest = _save_recording(external_id, audio, extension)
    call = Call(
        client_id=client.id,
        manager_id=manager.id,
        audio_path=str(dest),
        started_at=started_at,
        duration_sec=answered or 0,
        channels=2 if audio_name == "stereo" else 1,
        status=CallStatus.NEW,
    )
    session.add(call)
    session.flush()

    row.call_id = call.id
    row.status = AtcCallStatus.QUEUED
    row.note = ""
    session.flush()
    return AstResult(external_id=external_id, call_id=call.id, submit=True)


def _save_recording(external_id: str, audio: bytes, extension: str) -> Path:
    ext = extension if extension in AUDIO_EXTENSIONS else suffix_for(audio)
    folder = settings.DATA_DIR / "raw"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{external_id[:64]}_ast{ext}"
    dest.write_bytes(audio)
    secure.lock(dest)
    return dest


def _parse_time(value: object) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(float(value), tz=UTC)
    if isinstance(value, str) and value.strip().isdigit():
        return datetime.fromtimestamp(float(value.strip()), tz=UTC)
    return None


def _now() -> datetime:
    return datetime.now(ZoneInfo(settings.TZ))


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
