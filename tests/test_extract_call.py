"""Tests for extract_call agreement retention."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Agreement,
    AgreementResponsible,
    AgreementStatus,
    Base,
    Call,
    CallStatus,
    Client,
    Manager,
    SpeakerRole,
    Utterance,
)
from app.extraction.schema import ExtractedAgreement, ExtractionResult
from app.pipeline import extract_call


def test_extract_call_keeps_reviewed_agreements(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    monkeypatch.setattr("app.pipeline.SessionLocal", Session)

    reviewed_quote = "Мы оплатим до 20 числа."
    duplicate_quote = "Мы оплатим до 20 числа"
    new_quote = "Я вышлю КП до пятницы."

    def fake_extract(_utterances: list[Utterance], _started: datetime) -> ExtractionResult:
        return ExtractionResult(
            agreements=[
                ExtractedAgreement(
                    action="оплатить",
                    responsible="client",
                    due_text="до 20 числа",
                    quote=duplicate_quote,
                    utterance_index=1,
                ),
                ExtractedAgreement(
                    action="выслать КП",
                    responsible="manager",
                    due_text="до пятницы",
                    quote=new_quote,
                    utterance_index=0,
                ),
            ]
        )

    def fake_verify(
        _utterances: list[Utterance], agreements: list[ExtractedAgreement]
    ) -> list[ExtractedAgreement]:
        return agreements

    monkeypatch.setattr("app.pipeline.extract", fake_extract)
    monkeypatch.setattr("app.pipeline.verify_agreements", fake_verify)

    with Session() as session:
        client = Client(name="C", phone="+1")
        manager = Manager(name="M")
        session.add_all([client, manager])
        session.flush()
        call = Call(
            client_id=client.id,
            manager_id=manager.id,
            audio_path="x.wav",
            started_at=datetime(2026, 10, 9, tzinfo=UTC),
            duration_sec=60,
            channels=2,
            status=CallStatus.TRANSCRIBED,
        )
        session.add(call)
        session.flush()
        session.add(
            Utterance(
                call_id=call.id,
                speaker=SpeakerRole.MANAGER,
                start_sec=0,
                end_sec=1,
                text=new_quote,
            )
        )
        session.add(
            Utterance(
                call_id=call.id,
                speaker=SpeakerRole.CLIENT,
                start_sec=1,
                end_sec=2,
                text=reviewed_quote,
            )
        )
        session.add(
            Agreement(
                call_id=call.id,
                client_id=client.id,
                action="оплатить",
                responsible=AgreementResponsible.CLIENT,
                due_text="до 20 числа",
                quote=reviewed_quote,
                status=AgreementStatus.DONE,
            )
        )
        session.add(
            Agreement(
                call_id=call.id,
                client_id=client.id,
                action="устаревшее",
                responsible=AgreementResponsible.MANAGER,
                due_text="",
                quote="старое open",
                status=AgreementStatus.OPEN,
            )
        )
        session.commit()
        call_id = call.id

    extract_call(call_id)

    with Session() as session:
        agreements = session.scalars(
            select(Agreement).where(Agreement.call_id == call_id)
        ).all()
        assert len(agreements) == 2
        by_status = {a.status: a for a in agreements}
        assert AgreementStatus.DONE in by_status
        assert by_status[AgreementStatus.DONE].quote == reviewed_quote
        open_ag = next(a for a in agreements if a.status == AgreementStatus.OPEN)
        assert open_ag.quote == new_quote
