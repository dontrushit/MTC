"""Автосекретарь events: match the client, then wait for the recording URL."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import worker
from app.api.deps import get_db
from app.api.main import app
from app.atc.phones import normalize_phone
from app.config import settings
from app.db.models import Call, CallStatus
from tests.test_api import _bind_temp_db, _sign_in

WAV = b"RIFF$\x00\x00\x00WAVEfmt "


def test_normalize_phone_accepts_8_and_plus_7() -> None:
    assert normalize_phone("8 (916) 123-45-67") == "+79161234567"
    assert normalize_phone("+7 916 123 45 67") == "+79161234567"
    assert normalize_phone("9161234567") == "+79161234567"
    assert normalize_phone("101") == "101"
    assert normalize_phone("") == ""


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    factory = _bind_temp_db(tmp_path, monkeypatch)
    submitted: list[int] = []
    monkeypatch.setattr(worker, "submit_call", submitted.append)
    monkeypatch.setattr(settings, "ATC_BASIC_USER", "")
    monkeypatch.setattr(settings, "ATC_BASIC_PASSWORD", "")
    monkeypatch.setattr(settings, "ATC_RECORDING_URL", "")
    monkeypatch.setattr(settings, "ATC_MANAGER_ID", "")

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
            manager_id = _sign_in(client, factory)
            yield {
                "client": client,
                "submitted": submitted,
                "Session": factory,
                "manager_id": manager_id,
            }
    finally:
        app.dependency_overrides.clear()


def _manager(api: dict, name: str = "Анна", phone: str | None = None) -> dict:
    body: dict[str, str] = {"name": name}
    if phone is not None:
        body["phone"] = phone
    response = api["client"].post("/managers", json=body)
    assert response.status_code == 200
    return response.json()


def _post(api: dict, payload: dict) -> None:
    response = api["client"].post("/CallEvent", json=payload)
    assert response.status_code == 200
    assert response.json() == {}


def _upload(api: dict, external_id: str) -> dict:
    response = api["client"].post(
        f"/atc/calls/{external_id}/recording",
        files={"file": ("call.wav", WAV, "audio/wav")},
    )
    assert response.status_code == 200
    return response.json()


def test_call_waits_until_recording_is_attached(api: dict) -> None:
    _manager(api)
    _post(api, {"CallID": 501, "EventType": 1, "AN": "89161234567"})
    _post(api, {"CallID": 501, "EventType": 15})

    waiting = api["client"].get("/atc/calls/501")
    assert waiting.status_code == 200
    body = waiting.json()
    assert body["status"] == "waiting_recording"
    assert body["caller_phone"] == "+79161234567"
    assert body["call_id"] is None
    assert api["submitted"] == []

    attached = _upload(api, "501")
    assert attached["status"] == "queued"
    assert attached["call_id"] == api["submitted"][0]

    with api["Session"]() as session:
        call = session.get(Call, attached["call_id"])
        assert call is not None
        assert Path(call.audio_path).is_file()
        customer = call.client
        assert customer.name == "Неизвестный"
        assert customer.phone == "+79161234567"


def test_same_number_reuses_client_and_end_is_idempotent(api: dict) -> None:
    _manager(api)
    created = api["client"].post(
        "/clients",
        json={"name": "Иван", "last_name": "Петров", "phone": "+375291612345"},
    )
    assert created.status_code == 200
    client_id = created.json()["id"]

    _post(api, {"CallID": "700", "EventType": 1, "AN": "375291612345"})
    _upload(api, "700")
    _post(
        api,
        {
            "CallID": "700",
            "EventType": 15,
            "EventTime": "2026-10-10T12:00:00",
        },
    )
    _post(api, {"CallID": "700", "EventType": 26, "Duration": 42})
    assert len(api["submitted"]) == 1

    _post(api, {"CallID": "701", "EventType": 1, "AN": "+375 29 161-23-45"})
    _upload(api, "701")
    _post(api, {"CallID": "701", "EventType": 14})
    assert len(api["submitted"]) == 2

    with api["Session"]() as session:
        calls = list(session.scalars(select(Call).order_by(Call.id)).all())
        assert [item.client_id for item in calls] == [client_id, client_id]
        assert calls[0].duration_sec == 42
        assert calls[0].client.name == "Иван"


def test_agent_number_picks_the_manager(api: dict) -> None:
    _manager(api, name="Анна")
    boris = _manager(api, name="Борис", phone="101")
    _post(api, {"CallID": 9, "EventType": 1, "AN": "79160000000"})
    _post(api, {"CallID": 9, "EventType": 9, "Result": "1280", "DN1": "101"})
    _post(api, {"CallID": 9, "EventType": 9, "Result": "0", "DN1": "999"})
    _upload(api, "9")
    _post(api, {"CallID": 9, "EventType": 15})

    with api["Session"]() as session:
        call = session.scalars(select(Call)).one()
        assert call.manager_id == boris["id"]


def test_recording_url_downloads_after_the_answer(
    api: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    _manager(api)
    monkeypatch.setattr(settings, "ATC_RECORDING_URL", "https://example.test/{call_id}")
    monkeypatch.setattr("app.atc.recording.fetch_recording", lambda external_id: WAV)

    _post(api, {"CallID": 88, "EventType": 1, "AN": "79161112233"})
    _post(api, {"CallID": 88, "EventType": 15})

    assert api["submitted"] == [api["client"].get("/atc/calls/88").json()["call_id"]]
    assert api["client"].get("/atc/calls/88").json()["status"] == "queued"


def test_basic_auth_and_garbage_body(api: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ATC_BASIC_USER", "mts")
    monkeypatch.setattr(settings, "ATC_BASIC_PASSWORD", "secret")
    closed = api["client"].post("/CallEvent", json={"CallID": 1, "EventType": 1})
    assert closed.status_code == 401

    opened = api["client"].post(
        "/CallEvent",
        json={"CallID": 1, "EventType": 1, "AN": "79160000000"},
        auth=("mts", "secret"),
    )
    assert opened.status_code == 200
    garbage = api["client"].post(
        "/CallEvent",
        content=b"not-json",
        headers={"Content-Type": "application/json"},
        auth=("mts", "secret"),
    )
    assert garbage.status_code == 200
    assert garbage.json() == {}


def test_live_screen_shows_when_recording_starts(api: dict) -> None:
    idle = api["client"].get("/atc/live")
    assert idle.status_code == 200
    assert idle.json()["phase"] == "idle"

    _post(api, {"CallID": 42, "EventType": 1, "AN": "89161234567"})
    starting = api["client"].get("/atc/live").json()
    assert starting["phase"] == "starting"
    assert starting["recording_on"] is False
    assert starting["caller_phone"] == "+79161234567"

    _post(api, {"CallID": 42, "EventType": 13})
    recording = api["client"].get("/atc/live").json()
    assert recording["phase"] == "recording"
    assert recording["recording_on"] is True

    _post(api, {"CallID": 42, "EventType": 15})
    assert api["client"].get("/atc/live").json()["phase"] == "idle"


def test_history_shows_a_live_call_and_a_ready_report(api: dict) -> None:
    customer = api["client"].post(
        "/clients",
        json={"name": "Иван", "last_name": "Петров", "phone": "+375291612345"},
    ).json()
    _post(api, {"CallID": 77, "EventType": 1, "AN": "89160001122"})
    _post(api, {"CallID": 77, "EventType": 13})
    with api["Session"]() as session:
        call = Call(
            client_id=customer["id"],
            manager_id=api["manager_id"],
            audio_path="data/raw/ready.wav",
            started_at=datetime(2026, 10, 1, tzinfo=UTC),
            duration_sec=5,
            channels=1,
            status=CallStatus.EXTRACTED,
            report_topic="Симка",
        )
        session.add(call)
        session.commit()
        call_id = call.id

    rows = api["client"].get("/history")
    assert rows.status_code == 200
    body = rows.json()
    live = next(item for item in body if item["phone"] == "+79160001122")
    assert live["status"] == "recording"
    assert live["call_id"] is None
    assert live["client_name"] == ""
    ready = next(item for item in body if item["call_id"] == call_id)
    assert ready["status"] == "ready"
    assert ready["topic"] == "Симка"
    assert ready["client_name"] == "Иван Петров"

    _post(api, {"CallID": 77, "EventType": 15})
    _upload(api, "77")
    again = api["client"].get("/history").json()
    matched = [item for item in again if item["phone"] == "+79160001122"]
    assert len(matched) == 1
    assert matched[0]["status"] == "preparing"
    assert matched[0]["client_name"] == "Неизвестный"
    assert matched[0]["call_id"] is not None


def test_settings_screen_saves_the_pbx_connection(api: dict) -> None:
    manager = _manager(api, name="Анна")
    other = _manager(api, name="Борис")
    saved = api["client"].put(
        "/atc/settings",
        json={
            "public_url": "http://office.example:8000/",
            "basic_user": "mts",
            "basic_password": "secret",
            "recording_url": " https://files.example/{call_id} ",
            "manager_id": other["id"],
            "managers": [
                {"id": manager["id"], "name": "Мария", "phone": "101"},
                {"id": other["id"], "name": "Борис", "phone": "8 (916) 000-00-02"},
            ],
        },
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["event_url"] == "http://office.example:8000/CallEvent"
    assert body["recording_url"] == "https://files.example/{call_id}"
    assert body["manager_id"] == other["id"]
    phones = {item["name"]: item["phone"] for item in body["managers"]}
    assert phones["Мария"] == "101"
    assert phones["Борис"] == "+79160000002"

    closed = api["client"].post(
        "/CallEvent",
        json={"CallID": 5, "EventType": 1, "AN": "79160000000"},
    )
    assert closed.status_code == 401
    opened = api["client"].post(
        "/CallEvent",
        json={"CallID": 5, "EventType": 1, "AN": "79160000000"},
        auth=("mts", "secret"),
    )
    assert opened.status_code == 200
    missing = api["client"].put(
        "/atc/settings",
        json={"manager_id": 999, "managers": []},
    )
    assert missing.status_code == 400


def test_employee_sees_only_their_calls_and_not_the_pbx_settings(api: dict) -> None:
    employee = api["client"].post(
        "/managers",
        json={"name": "Олег", "password": "secret1"},
    )
    assert employee.status_code == 200
    signed = api["client"].post("/auth/login", json={"name": "Олег", "password": "secret1"})
    assert signed.status_code == 200
    token = signed.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    denied = api["client"].get("/atc/settings", headers=headers)
    assert denied.status_code == 403
    history = api["client"].get("/history", headers=headers)
    assert history.status_code == 200
    assert history.json() == []


def test_recording_is_queued_for_the_signed_in_employee(api: dict) -> None:
    _post(api, {"CallID": 3, "EventType": 1, "AN": "79160000000"})
    _post(api, {"CallID": 3, "EventType": 15})
    attached = _upload(api, "3")
    assert attached["status"] == "queued"
    assert attached["call_id"] == api["submitted"][0]
