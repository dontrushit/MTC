"""End-to-end call processing: audio prep, ASR, extraction, persist."""

from __future__ import annotations

import json
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select

from app.asr.merge import merge_dialog
from app.asr.roles import resolve_roles
from app.asr.transcribe import transcribe_channel
from app.audio.preprocess import prepare_channels
from app.audio.probe import probe
from app.audio.vad import speech_segments
from app.config import settings
from app.db.models import (
    Agreement,
    AgreementResponsible,
    AgreementStatus,
    Call,
    CallStatus,
    SpeakerRole,
    Utterance,
)
from app.db.session import SessionLocal
from app.extraction.dates import resolve_due
from app.extraction.llm import extract
from app.extraction.verify import normalize_quote, verify_agreements


def process_call(call_id: int) -> None:
    """Transcribe a call by id, extract agreements, persist (idempotent on re-run)."""
    session = SessionLocal()
    try:
        call = session.get(Call, call_id)
        if call is None:
            msg = f"Call {call_id} not found"
            raise ValueError(msg)

        call.status = CallStatus.PROCESSING
        call.error_message = None
        session.commit()

        audio_path = Path(call.audio_path)
        info = probe(audio_path)
        call.duration_sec = int(round(info.duration_sec))
        call.channels = info.channels

        out_dir = settings.DATA_DIR / "processed" / str(call_id)
        channel_paths = prepare_channels(audio_path, out_dir)

        speech_segments(channel_paths[SpeakerRole.MANAGER])
        speech_segments(channel_paths[SpeakerRole.CLIENT])

        segs_manager = transcribe_channel(
            channel_paths[SpeakerRole.MANAGER], SpeakerRole.MANAGER
        )
        segs_client = transcribe_channel(
            channel_paths[SpeakerRole.CLIENT], SpeakerRole.CLIENT
        )
        dialog = resolve_roles(merge_dialog(segs_manager, segs_client))

        session.execute(delete(Utterance).where(Utterance.call_id == call_id))
        for seg in dialog:
            session.add(
                Utterance(
                    call_id=call_id,
                    speaker=seg.speaker,
                    start_sec=seg.start,
                    end_sec=seg.end,
                    text=seg.text,
                )
            )

        call.status = CallStatus.TRANSCRIBED
        session.commit()

        extract_call(call_id)
    except Exception as exc:
        session.rollback()
        call = session.get(Call, call_id)
        if call is not None:
            call.status = CallStatus.ERROR
            call.error_message = str(exc)
            session.commit()
    finally:
        session.close()


def extract_call(call_id: int) -> None:
    """Extract agreements for a transcribed call (idempotent)."""
    session = SessionLocal()
    tz = ZoneInfo(settings.TZ)
    try:
        call = session.get(Call, call_id)
        if call is None:
            msg = f"Call {call_id} not found"
            raise ValueError(msg)
        if call.status not in (CallStatus.TRANSCRIBED, CallStatus.EXTRACTED):
            msg = f"Call {call_id} must be transcribed before extraction (status={call.status})"
            raise ValueError(msg)

        utterances = list(
            session.scalars(
                select(Utterance)
                .where(Utterance.call_id == call_id)
                .order_by(Utterance.start_sec)
            ).all()
        )

        result = extract(utterances, call.started_at)
        verified = verify_agreements(utterances, result.agreements)

        existing = list(
            session.scalars(select(Agreement).where(Agreement.call_id == call_id)).all()
        )
        reviewed_keys = {
            (a.responsible, normalize_quote(a.quote))
            for a in existing
            if a.status != AgreementStatus.OPEN
        }

        session.execute(
            delete(Agreement).where(
                Agreement.call_id == call_id,
                Agreement.status == AgreementStatus.OPEN,
            )
        )

        for ag in verified:
            resp = AgreementResponsible(ag.responsible)
            key = (resp, normalize_quote(ag.quote))
            if key in reviewed_keys:
                continue
            due_text = ag.due_text or ""
            due_date = resolve_due(ag.due_text, call.started_at, tz)
            session.add(
                Agreement(
                    call_id=call_id,
                    client_id=call.client_id,
                    action=ag.action,
                    responsible=resp,
                    due_date=due_date,
                    due_text=due_text,
                    amount=ag.amount,
                    conditions=ag.conditions,
                    quote=ag.quote,
                )
            )

        report = {
            "topic": result.topic.strip(),
            "brief": result.brief.strip(),
            "unresolved": result.unresolved.strip(),
        }
        call.report_topic = report["topic"]
        call.report_summary = report["brief"]
        call.report_json = json.dumps(report, ensure_ascii=False)
        call.status = CallStatus.EXTRACTED
        call.error_message = None
        session.commit()
    except Exception as exc:
        session.rollback()
        call = session.get(Call, call_id)
        if call is not None:
            call.status = CallStatus.ERROR
            call.error_message = str(exc)
            session.commit()
        raise
    finally:
        session.close()
