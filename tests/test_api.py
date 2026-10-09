"""API tests on a temporary SQLite database. submit_call is mocked."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import worker
from app.api.deps import get_db
from app.api.main import app
from app.config import settings
from app.db import session as db_session
from app.db.models import (
    Agreement,
    AgreementResponsible,
    AgreementStatus,
    Call,
    CallStatus,
    Client,
    Manager,
    SpeakerRole,
    Utterance,
)
from app.db.session import init_db

TZ = ZoneInfo("Europe/Moscow")


def _today():
    return datetime.now(TZ).date()


def _bind_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = tmp_path / "data"
    (data_dir / "raw").mkdir(parents=True)
    monkeypatch.setattr(settings, "DATA_DIR", data_dir)
    url = f"sqlite:///{tmp_path / 'api.db'}"
    monkeypatch.setattr(settings, "DB_URL", url)
    engine = create_engine(url, connect_args={"check_same_thread": False})
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "SessionLocal", factory)
    return factory


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    factory = _bind_temp_db(tmp_path, monkeypatch)
    submitted: list[int] = []

    def _fake_submit(call_id: int) -> None:
        submitted.append(call_id)

    monkeypatch.setattr(worker, "submit_call", _fake_submit)

    def _override():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override
    try:
        with TestClient(app) as client:
            yield {"client": client, "submitted": submitted, "Session": factory}
    finally:
        app.dependency_overrides.clear()


def _manager(api: dict, name: str = "Анна") -> dict:
    response = api["client"].post("/managers", json={"name": name})
    assert response.status_code == 200
    return response.json()


def _customer(api: dict) -> dict:
    response = api["client"].post(
        "/clients",
        json={"name": "Иван", "last_name": "Петров", "phone": "+74951234567"},
    )
    assert response.status_code == 200
    return response.json()


def test_create_manager_and_client(api: dict) -> None:
    manager = _manager(api)
    assert manager["name"] == "Анна"
    assert manager["is_supervisor"] is False
    listed = api["client"].get("/managers")
    assert listed.status_code == 200
    assert [item["name"] for item in listed.json()] == ["Анна"]

    customer = _customer(api)
    assert customer["name"] == "Иван"
    assert customer["last_name"] == "Петров"
    assert customer["phone"] == "+74951234567"
    found = api["client"].get("/clients", params={"q": "петров"})
    assert [item["id"] for item in found.json()] == [customer["id"]]
    by_phone = api["client"].get("/clients", params={"q": "495123"})
    assert [item["id"] for item in by_phone.json()] == [customer["id"]]


def test_clients_sort_by_name_surname_and_call(api: dict) -> None:
    manager = _manager(api)
    boris = api["client"].post(
        "/clients", json={"name": "Борис", "last_name": "Яковлев", "phone": "+79000000001"}
    ).json()
    anna = api["client"].post(
        "/clients", json={"name": "Анна", "last_name": "Андреева", "phone": "+79000000002"}
    ).json()
    api["client"].post(
        "/calls",
        data={
            "client_id": str(boris["id"]),
            "manager_id": str(manager["id"]),
            "started_at": "2026-10-01T10:00:00",
        },
        files={"file": ("old.wav", b"RIFFold", "audio/wav")},
    )
    api["client"].post(
        "/calls",
        data={
            "client_id": str(anna["id"]),
            "manager_id": str(manager["id"]),
            "started_at": "2026-10-08T10:00:00",
        },
        files={"file": ("new.wav", b"RIFFnew", "audio/wav")},
    )

    by_name = api["client"].get("/clients", params={"sort": "name"})
    assert [item["name"] for item in by_name.json()] == ["Анна", "Борис"]
    by_surname = api["client"].get("/clients", params={"sort": "last_name"})
    assert [item["last_name"] for item in by_surname.json()] == ["Андреева", "Яковлев"]
    by_call = api["client"].get("/clients", params={"sort": "call"})
    assert [item["id"] for item in by_call.json()] == [anna["id"], boris["id"]]
    assert api["client"].get("/clients", params={"sort": "nope"}).status_code == 400


def test_upload_call_saves_file_and_submits(api: dict) -> None:
    manager = _manager(api)
    customer = _customer(api)
    response = api["client"].post(
        "/calls",
        data={
            "client_id": str(customer["id"]),
            "manager_id": str(manager["id"]),
            "started_at": "2026-10-09T11:00:00",
        },
        files={"file": ("talk.wav", b"RIFFdemo", "audio/wav")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "new"
    assert body["started_at"].startswith("2026-10-09T11:00:00")
    path = Path(body["audio_path"])
    assert path.is_file()
    assert path.name == f"{body['id']}_talk.wav"
    assert path.read_bytes() == b"RIFFdemo"
    assert api["submitted"] == [body["id"]]

    audio = api["client"].get(f"/calls/{body['id']}/audio")
    assert audio.status_code == 200
    assert audio.content == b"RIFFdemo"

    again = api["client"].post(f"/calls/{body['id']}/reprocess")
    assert again.status_code == 200
    assert again.json()["status"] == "new"
    assert api["submitted"] == [body["id"], body["id"]]


def test_upload_rejects_bad_extension(api: dict) -> None:
    manager = _manager(api)
    customer = _customer(api)
    response = api["client"].post(
        "/calls",
        data={"client_id": str(customer["id"]), "manager_id": str(manager["id"])},
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
    assert api["submitted"] == []


def test_upload_unknown_client(api: dict) -> None:
    manager = _manager(api)
    response = api["client"].post(
        "/calls",
        data={"client_id": "999", "manager_id": str(manager["id"])},
        files={"file": ("talk.wav", b"RIFFdemo", "audio/wav")},
    )
    assert response.status_code == 404
    assert api["submitted"] == []


def test_call_detail_returns_utterances_and_agreements(api: dict) -> None:
    started = datetime(2026, 10, 9, 11, 0, tzinfo=TZ)
    with api["Session"]() as session:
        customer = Client(name="ООО Ромашка", phone="+74951234567", company="Ромашка")
        manager = Manager(name="Анна")
        session.add_all([customer, manager])
        session.flush()
        call = Call(
            client_id=customer.id,
            manager_id=manager.id,
            audio_path="data/raw/manual.wav",
            started_at=started,
            duration_sec=30,
            channels=2,
            status=CallStatus.EXTRACTED,
        )
        session.add(call)
        session.flush()
        session.add_all(
            [
                Utterance(
                    call_id=call.id,
                    speaker=SpeakerRole.MANAGER,
                    start_sec=0.0,
                    end_sec=2.0,
                    text="Вышлю коммерческое предложение до пятницы.",
                ),
                Utterance(
                    call_id=call.id,
                    speaker=SpeakerRole.CLIENT,
                    start_sec=2.0,
                    end_sec=4.0,
                    text="Жду.",
                ),
                Agreement(
                    call_id=call.id,
                    client_id=customer.id,
                    action="Выслать КП",
                    responsible=AgreementResponsible.MANAGER,
                    due_date=_today() + timedelta(days=1),
                    due_text="до пятницы",
                    quote="Вышлю коммерческое предложение до пятницы.",
                ),
            ]
        )
        session.commit()
        call_id = call.id

    response = api["client"].get(f"/calls/{call_id}")
    assert response.status_code == 200
    body = response.json()
    assert [item["speaker"] for item in body["utterances"]] == ["manager", "client"]
    assert body["utterances"][0]["text"].startswith("Вышлю")
    assert body["agreements"][0]["quote"].startswith("Вышлю")
    assert body["agreements"][0]["action"] == "Выслать КП"


def test_patch_agreement_status(api: dict) -> None:
    with api["Session"]() as session:
        customer = Client(name="ООО Ромашка", phone="+74951234567")
        manager = Manager(name="Анна")
        session.add_all([customer, manager])
        session.flush()
        call = Call(
            client_id=customer.id,
            manager_id=manager.id,
            audio_path="data/raw/manual.wav",
            started_at=datetime.now(UTC),
            duration_sec=10,
            channels=2,
        )
        session.add(call)
        session.flush()
        agreement = Agreement(
            call_id=call.id,
            client_id=customer.id,
            action="Перезвонить",
            responsible=AgreementResponsible.MANAGER,
            due_date=_today() + timedelta(days=3),
            due_text="завтра",
            quote="Завтра перезвоню.",
        )
        session.add(agreement)
        session.commit()
        agreement_id = agreement.id

    response = api["client"].patch(f"/agreements/{agreement_id}", json={"status": "done"})
    assert response.status_code == 200
    assert response.json()["status"] == "done"

    listed = api["client"].get("/agreements", params={"status": "done"})
    assert [item["id"] for item in listed.json()] == [agreement_id]


def test_mark_overdue_moves_past_open_agreements(api: dict) -> None:
    today = _today()
    with api["Session"]() as session:
        customer = Client(name="ООО Ромашка", phone="+74951234567")
        manager = Manager(name="Анна")
        session.add_all([customer, manager])
        session.flush()
        call = Call(
            client_id=customer.id,
            manager_id=manager.id,
            audio_path="data/raw/manual.wav",
            started_at=datetime.now(UTC),
            duration_sec=10,
            channels=2,
        )
        session.add(call)
        session.flush()
        session.add_all(
            [
                Agreement(
                    call_id=call.id,
                    client_id=customer.id,
                    action="просрочить",
                    responsible=AgreementResponsible.MANAGER,
                    due_date=today - timedelta(days=1),
                    due_text="вчера",
                    quote="Сделаю вчера.",
                ),
                Agreement(
                    call_id=call.id,
                    client_id=customer.id,
                    action="ещё открыта",
                    responsible=AgreementResponsible.CLIENT,
                    due_date=today + timedelta(days=2),
                    due_text="послезавтра",
                    quote="Оплачу послезавтра.",
                ),
                Agreement(
                    call_id=call.id,
                    client_id=customer.id,
                    action="уже выполнена",
                    responsible=AgreementResponsible.MANAGER,
                    due_date=today - timedelta(days=3),
                    due_text="давно",
                    quote="Уже отправил.",
                    status=AgreementStatus.DONE,
                ),
            ]
        )
        session.commit()
        client_id = customer.id

    listed = api["client"].get("/agreements")
    assert listed.status_code == 200
    by_action = {item["action"]: item["status"] for item in listed.json()}
    assert by_action["просрочить"] == "overdue"
    assert by_action["ещё открыта"] == "open"
    assert by_action["уже выполнена"] == "done"

    card = api["client"].get(f"/clients/{client_id}")
    card_status = {item["action"]: item["status"] for item in card.json()["agreements"]}
    assert card_status["просрочить"] == "overdue"
    assert card.json()["agreements"][0]["status"] == "overdue"


def test_manager_stats(api: dict) -> None:
    today = _today()
    with api["Session"]() as session:
        anna = Manager(name="Анна")
        boris = Manager(name="Борис")
        customer = Client(name="ООО Ромашка", phone="+74951234567")
        session.add_all([anna, boris, customer])
        session.flush()
        call = Call(
            client_id=customer.id,
            manager_id=anna.id,
            audio_path="data/raw/manual.wav",
            started_at=datetime.now(UTC),
            duration_sec=10,
            channels=2,
            status=CallStatus.EXTRACTED,
        )
        session.add(call)
        session.flush()
        session.add_all(
            [
                Agreement(
                    call_id=call.id,
                    client_id=customer.id,
                    action="открытая",
                    responsible=AgreementResponsible.MANAGER,
                    due_date=today + timedelta(days=2),
                    due_text="скоро",
                    quote="Сделаю скоро.",
                ),
                Agreement(
                    call_id=call.id,
                    client_id=customer.id,
                    action="станет просроченной",
                    responsible=AgreementResponsible.MANAGER,
                    due_date=today - timedelta(days=1),
                    due_text="вчера",
                    quote="Должен был вчера.",
                ),
                Agreement(
                    call_id=call.id,
                    client_id=customer.id,
                    action="вовремя",
                    responsible=AgreementResponsible.MANAGER,
                    due_date=today + timedelta(days=1),
                    due_text="завтра",
                    quote="Успею завтра.",
                    status=AgreementStatus.DONE,
                ),
                Agreement(
                    call_id=call.id,
                    client_id=customer.id,
                    action="с опозданием",
                    responsible=AgreementResponsible.CLIENT,
                    due_date=today - timedelta(days=2),
                    due_text="позавчера",
                    quote="Оплачу позавчера.",
                    status=AgreementStatus.DONE,
                ),
                Agreement(
                    call_id=call.id,
                    client_id=customer.id,
                    action="отменена",
                    responsible=AgreementResponsible.MANAGER,
                    due_date=today - timedelta(days=1),
                    due_text="не надо",
                    quote="Отменяем.",
                    status=AgreementStatus.CANCELLED,
                ),
            ]
        )
        session.commit()

    response = api["client"].get("/stats/managers")
    assert response.status_code == 200
    rows = {item["name"]: item for item in response.json()}
    assert rows["Анна"]["open"] == 1
    assert rows["Анна"]["overdue"] == 1
    assert rows["Анна"]["done"] == 2
    assert rows["Анна"]["done_on_time"] == 50.0
    assert rows["Борис"]["open"] == 0
    assert rows["Борис"]["overdue"] == 0
    assert rows["Борис"]["done"] == 0
    assert rows["Борис"]["done_on_time"] is None


def test_startup_requeues_processing_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    factory = _bind_temp_db(tmp_path, monkeypatch)
    init_db()
    with factory() as session:
        customer = Client(name="ООО Ромашка", phone="+74951234567")
        manager = Manager(name="Анна")
        session.add_all([customer, manager])
        session.flush()
        call = Call(
            client_id=customer.id,
            manager_id=manager.id,
            audio_path="data/raw/stuck.wav",
            started_at=datetime.now(UTC),
            duration_sec=5,
            channels=2,
            status=CallStatus.PROCESSING,
        )
        session.add(call)
        session.commit()
        call_id = call.id

    submitted: list[int] = []
    monkeypatch.setattr(worker, "submit_call", lambda cid: submitted.append(cid))
    with TestClient(app):
        pass
    assert submitted == [call_id]


def test_update_client(api: dict) -> None:
    customer = _customer(api)
    patched = api["client"].patch(
        f"/clients/{customer['id']}",
        json={"name": "Мария", "last_name": "Иванова", "phone": "+79001112233"},
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["name"] == "Мария"
    assert body["last_name"] == "Иванова"
    assert body["phone"] == "+79001112233"

    blank = api["client"].patch(
        f"/clients/{customer['id']}",
        json={"name": " ", "last_name": "Иванова", "phone": "+79001112233"},
    )
    assert blank.status_code == 400
    missing = api["client"].patch(
        "/clients/99999",
        json={"name": "А", "last_name": "Б", "phone": "1"},
    )
    assert missing.status_code == 404


def test_delete_client_removes_calls_and_file(api: dict) -> None:
    manager = _manager(api)
    customer = _customer(api)
    uploaded = api["client"].post(
        "/calls",
        data={"client_id": str(customer["id"]), "manager_id": str(manager["id"])},
        files={"file": ("talk.wav", b"RIFFdemo", "audio/wav")},
    )
    assert uploaded.status_code == 200
    call_id = uploaded.json()["id"]
    audio_path = Path(uploaded.json()["audio_path"])
    assert audio_path.is_file()

    removed = api["client"].delete(f"/clients/{customer['id']}")
    assert removed.status_code == 204
    assert api["client"].get(f"/clients/{customer['id']}").status_code == 404
    assert api["client"].get(f"/calls/{call_id}").status_code == 404
    assert not audio_path.exists()


def test_delete_one_call(api: dict) -> None:
    manager = _manager(api)
    customer = _customer(api)
    uploaded = api["client"].post(
        "/calls",
        data={"client_id": str(customer["id"]), "manager_id": str(manager["id"])},
        files={"file": ("one.wav", b"RIFFone", "audio/wav")},
    )
    call_id = uploaded.json()["id"]
    removed = api["client"].delete(f"/calls/{call_id}")
    assert removed.status_code == 204
    assert api["client"].get(f"/calls/{call_id}").status_code == 404
    assert api["client"].get(f"/clients/{customer['id']}").status_code == 200
    assert api["client"].delete("/calls/99999").status_code == 404

