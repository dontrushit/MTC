"""ORM model and relationship tests on in-memory SQLite."""

from datetime import UTC, date, datetime

from sqlalchemy import create_engine
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


def test_create_call_graph_with_defaults() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        client = Client(name="Иван Петров", phone="+79001234567", company="ООО Ромашка")
        manager = Manager(name="Анна Менеджер", is_supervisor=False)
        session.add_all([client, manager])
        session.flush()

        started = datetime(2025, 10, 1, 10, 0, tzinfo=UTC)
        call = Call(
            client_id=client.id,
            manager_id=manager.id,
            audio_path="data/raw/call_001.wav",
            started_at=started,
            duration_sec=120,
            channels=2,
        )
        session.add(call)
        session.flush()

        session.add_all(
            [
                Utterance(
                    call_id=call.id,
                    speaker=SpeakerRole.MANAGER,
                    start_sec=0.0,
                    end_sec=3.5,
                    text="Договорились отправить КП до пятницы.",
                ),
                Utterance(
                    call_id=call.id,
                    speaker=SpeakerRole.CLIENT,
                    start_sec=3.5,
                    end_sec=6.0,
                    text="Жду, спасибо.",
                ),
            ]
        )

        agreement = Agreement(
            call_id=call.id,
            client_id=client.id,
            action="Отправить коммерческое предложение",
            responsible=AgreementResponsible.MANAGER,
            due_date=date(2025, 10, 3),
            due_text="до пятницы",
            quote="Договорились отправить КП до пятницы.",
        )
        session.add(agreement)
        session.commit()

        session.expire_all()
        loaded_call = session.get(Call, call.id)
        assert loaded_call is not None
        assert loaded_call.status == CallStatus.NEW
        assert loaded_call.client.name == "Иван Петров"
        assert loaded_call.manager.name == "Анна Менеджер"
        assert len(loaded_call.utterances) == 2
        assert loaded_call.utterances[0].speaker == SpeakerRole.MANAGER

        loaded_agreement = loaded_call.agreements[0]
        assert loaded_agreement.status == AgreementStatus.OPEN
        assert loaded_agreement.client_id == client.id
        assert loaded_agreement.due_text == "до пятницы"
        assert loaded_agreement.created_at is not None
        assert loaded_agreement.updated_at is not None
