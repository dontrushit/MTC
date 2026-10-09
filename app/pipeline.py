"""End-to-end call processing: audio prep, ASR, persist utterances."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete

from app.asr.merge import merge_dialog
from app.asr.transcribe import transcribe_channel
from app.audio.preprocess import split_channels
from app.audio.probe import probe
from app.audio.vad import speech_segments
from app.config import settings
from app.db.models import Call, CallStatus, SpeakerRole, Utterance
from app.db.session import SessionLocal


def process_call(call_id: int) -> None:
    """Transcribe a call by id and store utterances (idempotent on re-run)."""
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
        channel_paths = split_channels(audio_path, out_dir)

        speech_segments(channel_paths[SpeakerRole.MANAGER])
        speech_segments(channel_paths[SpeakerRole.CLIENT])

        segs_manager = transcribe_channel(
            channel_paths[SpeakerRole.MANAGER], SpeakerRole.MANAGER
        )
        segs_client = transcribe_channel(
            channel_paths[SpeakerRole.CLIENT], SpeakerRole.CLIENT
        )
        dialog = merge_dialog(segs_manager, segs_client)

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
    except Exception as exc:
        session.rollback()
        call = session.get(Call, call_id)
        if call is not None:
            call.status = CallStatus.ERROR
            call.error_message = str(exc)
            session.commit()
    finally:
        session.close()
