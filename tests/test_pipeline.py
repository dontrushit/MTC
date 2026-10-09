"""Slow integration test for process_call."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Call, CallStatus, Client, Manager, Utterance


@pytest.mark.slow
def test_process_call_test_recording(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wav = Path("data/raw/test_call.wav")
    if not wav.is_file():
        pytest.skip("data/raw/test_call.wav not found; run scripts/make_test_call.py")

    db_path = tmp_path / "mtc.db"
    data_dir = tmp_path / "data"
    monkeypatch.setattr(settings, "DB_URL", f"sqlite:///{db_path}")
    monkeypatch.setattr(settings, "DATA_DIR", data_dir)

    import app.db.session as db_session

    importlib.reload(db_session)
    import app.pipeline as pipeline

    importlib.reload(pipeline)

    db_session.init_db()
    Session = sessionmaker(bind=db_session.engine)
    with Session() as session:
        client = Client(name="Test Client", phone="+70000000000")
        manager = Manager(name="Test Manager")
        session.add_all([client, manager])
        session.flush()
        call = Call(
            client_id=client.id,
            manager_id=manager.id,
            audio_path=str(wav.resolve()),
            started_at=datetime.now(UTC),
            duration_sec=0,
            channels=0,
        )
        session.add(call)
        session.commit()
        call_id = call.id

    pipeline.process_call(call_id)

    with Session() as session:
        loaded = session.get(Call, call_id)
        assert loaded is not None
        assert loaded.status == CallStatus.TRANSCRIBED
        assert loaded.channels == 2
        assert loaded.duration_sec > 0
        utterances = session.scalars(select(Utterance).where(Utterance.call_id == call_id)).all()
        assert len(utterances) >= 2
        assert loaded.error_message is None
