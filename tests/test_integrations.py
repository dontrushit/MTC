"""Calendar export, CRM webhook, rule-based types, consent, and the audit log."""

from __future__ import annotations

from datetime import date, datetime
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
from app.db.models import Manager
from app.integrations.ics import build_ics
from app.rules import classify

TZ = ZoneInfo("Europe/Moscow")


def _bind_temp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> sessionmaker:
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

    def _fake_submit(call_id: int) -> None:
        return None

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
            _sign_in(client, factory)
            yield {"client": client, "Session": factory}
    finally:
        app.dependency_overrides.clear()


def _sign_in(client: TestClient, factory) -> None:
    from app.auth import hash_password

    with factory() as session:
        session.add(
            Manager(name="Служебный", password_hash=hash_password("test-pass"), is_supervisor=True)
        )
        session.commit()
    token = client.post(
        "/auth/login", json={"name": "Служебный", "password": "test-pass"}
    ).json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"


def _customer(api: dict) -> int:
    body = api["client"].post(
        "/clients", json={"name": "Иван", "last_name": "Петров", "phone": "+375291234567"}
    ).json()
    return int(body["id"])


def _call_with_agreement(api: dict, action: str = "Прислать КП до пятницы") -> tuple[int, int]:
    customer = _customer(api)
    body = api["client"].post(
        "/calls",
        data={
            "client_id": str(customer),
            "manager_id": str(_first_manager(api)),
            "started_at": "2026-10-09T11:00:00",
            "consent": "true",
        },
        files={"file": ("talk.wav", b"RIFFdemo", "audio/wav")},
    ).json()
    agreement = api["client"].post(
        f"/calls/{body['id']}/agreements",
        json={"action": action, "responsible": "manager", "due_text": ""},
    ).json()
    return int(body["id"]), int(agreement["id"])


def _first_manager(api: dict) -> int:
    return int(api["client"].get("/managers").json()[-1]["id"])


# --- unit parts -------------------------------------------------------------


def test_classify_matches_keywords() -> None:
    rules = [
        {"keywords": ["оплат"], "category": "оплата", "priority": "high"},
        {"keywords": ["кп"], "category": "КП", "priority": "normal"},
    ]
    assert classify("Прислать КП до пятницы", rules) == ("КП", "normal")
    assert classify("Жду оплату через неделю", rules) == ("оплата", "high")
    assert classify("Ничего подходящего", rules) == ("", "normal")


def test_build_ics_contains_event_and_escaping() -> None:
    body = build_ics(
        agreement_id=7,
        action="Позвонить, обсудить",
        client_name="Иван Петров",
        responsible="manager",
        due_date=date(2026, 10, 16),
        due_text="до пятницы",
        amount="100 руб.",
        conditions=None,
        quote="позвоню в пятницу",
        fallback=datetime(2026, 10, 9, 11, 0, tzinfo=TZ),
    )
    assert "BEGIN:VEVENT" in body
    assert "UID:agreement-7@mtc.local" in body
    assert "DTSTART;VALUE=DATE:20261016" in body
    assert "SUMMARY:Иван Петров: Позвонить\\, обсудить" in body
    assert "END:VCALENDAR" in body


# --- API --------------------------------------------------------------------


def test_agreement_ics_download_and_audit(api: dict) -> None:
    _call_id, agreement_id = _call_with_agreement(api)
    response = api["client"].get(f"/agreements/{agreement_id}/calendar.ics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VEVENT" in response.text

    audit = api["client"].get("/audit").json()
    assert any(
        row["action"] == "download_ics" and row["entity_id"] == agreement_id for row in audit
    )


def test_create_call_saves_consent_flag(api: dict) -> None:
    customer = _customer(api)
    body = api["client"].post(
        "/calls",
        data={
            "client_id": str(customer),
            "manager_id": str(_first_manager(api)),
            "started_at": "2026-10-09T11:00:00",
            "consent": "true",
        },
        files={"file": ("talk.wav", b"RIFFdemo", "audio/wav")},
    ).json()
    assert body["consent"] is True

    detail = api["client"].get(f"/calls/{body['id']}").json()
    assert detail["consent"] is True
    audit = api["client"].get("/audit").json()
    assert any(row["action"] == "consent" for row in audit)


def test_consent_can_be_marked_later(api: dict) -> None:
    customer = _customer(api)
    body = api["client"].post(
        "/calls",
        data={
            "client_id": str(customer),
            "manager_id": str(_first_manager(api)),
            "started_at": "2026-10-09T11:00:00",
        },
        files={"file": ("talk.wav", b"RIFFdemo", "audio/wav")},
    ).json()
    assert body["consent"] is False
    patched = api["client"].patch(f"/calls/{body['id']}/consent", json={"consent": True})
    assert patched.status_code == 200
    assert patched.json()["consent"] is True


def test_rules_endpoints_save_and_shapes_agreements(api: dict) -> None:
    saved = api["client"].put(
        "/agreement-rules",
        json={
            "rules": [
                {"keywords": ["кп"], "category": "КП", "priority": "high"},
                {"keywords": ["оплат"], "category": "оплата", "priority": "low"},
            ]
        },
    )
    assert saved.status_code == 200
    assert saved.json()["rules"][0]["priority"] == "high"

    _call_id, agreement_id = _call_with_agreement(api)
    agreement = api["client"].get(f"/calls/{_call_id}").json()["agreements"][0]
    assert agreement["category"] == "КП"
    assert agreement["priority"] == "high"

    patched = api["client"].patch(
        f"/agreements/{agreement_id}", json={"action": "Жду оплату во вторник"}
    )
    fresh = api["client"].get(f"/calls/{_call_id}").json()["agreements"][0]
    assert fresh["category"] == "оплата"
    assert fresh["priority"] == "low"
    assert patched.json()["action"] == "Жду оплату во вторник"

    broken = api["client"].put(
        "/agreement-rules", json={"rules": [{"keywords": ["x"], "category": "нонсенсе"}]}
    )
    assert broken.status_code == 400


def test_crm_settings_and_send(api: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    api["client"].put(
        "/crm/settings", json={"webhook_url": "https://crm.example/hook", "token": "secret"}
    )
    options = api["client"].get("/crm/settings").json()
    assert options["webhook_url"] == "https://crm.example/hook"

    seen: dict = {}

    def fake_send(url: str, payload: dict, *, token: str = "", timeout: float = 10.0):
        seen["url"] = url
        seen["token"] = token
        seen["payload"] = payload
        return True, "CRM приняла задачу (200)"

    import app.api.main as module

    monkeypatch.setattr(module, "send_to_crm", fake_send)
    _call_id, agreement_id = _call_with_agreement(api)
    result = api["client"].post(f"/agreements/{agreement_id}/send-to-crm")
    assert result.status_code == 200
    assert result.json() == {"sent": True, "message": "CRM приняла задачу (200)"}
    assert seen["url"] == "https://crm.example/hook"
    assert seen["token"] == "secret"
    assert seen["payload"]["action"] == "Прислать КП до пятницы"
    assert seen["payload"]["client_name"] == "Иван Петров"

    audit = api["client"].get("/audit").json()
    assert any(row["action"] == "send_crm" for row in audit)


def test_crm_without_url_fails_kindly(api: dict) -> None:
    _call_id, agreement_id = _call_with_agreement(api)
    result = api["client"].post(f"/agreements/{agreement_id}/send-to-crm")
    assert result.status_code == 409
    assert "CRM" in result.json()["detail"]


def test_opening_a_call_is_journaled(api: dict) -> None:
    call_id, agreement_id = _call_with_agreement(api)
    edited = api["client"].patch(f"/agreements/{agreement_id}", json={"status": "done"})
    assert edited.status_code == 200
    api["client"].get(f"/calls/{call_id}")
    audit = api["client"].get("/audit").json()
    actions = [row["action"] for row in audit]
    assert "open_call" in actions
    assert "edit_agreement" in actions


def test_worker_marks_call_error_when_pipeline_breaks(
    api: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken pipeline (e.g. no ASR module) must leave an honest error status."""
    import sys

    from app.api import worker
    from app.db.models import Call, CallStatus

    customer = _customer(api)
    with api["Session"]() as session:
        call = Call(
            client_id=customer,
            manager_id=1,
            audio_path="pending",
            started_at=datetime(2026, 10, 9, 11, 0, tzinfo=TZ),
            duration_sec=0,
            channels=0,
            status=CallStatus.NEW,
        )
        session.add(call)
        session.commit()
        call_id = call.id

    monkeypatch.setitem(sys.modules, "app.pipeline", None)
    worker._run(call_id)

    with api["Session"]() as session:
        call = session.get(Call, call_id)
        assert call.status == CallStatus.ERROR
        assert call.error_message and "app.pipeline" in call.error_message


def test_unknown_route_hidden_from_non_supervisors(api: dict, monkeypatch) -> None:
    """Only the supervisor sees stats; a normal manager gets 403."""
    from app.auth import hash_password
    from app.db.models import Manager

    with api["Session"]() as session:
        session.add(Manager(name="Рядовой", password_hash=hash_password("staff-pass")))
        session.commit()
    client = api["client"]
    client.headers.pop("Authorization")
    login = client.post(
        "/auth/login", json={"name": "Рядовой", "password": "staff-pass"}
    ).json()["token"]
    client.headers["Authorization"] = f"Bearer {login}"
    assert client.get("/stats/agreements").status_code == 403
    assert client.get("/audit").status_code == 403

    boss = client.post(
        "/auth/login", json={"name": "Служебный", "password": "test-pass"}
    ).json()["token"]
    client.headers["Authorization"] = f"Bearer {boss}"
    _call_with_agreement(api)
    overview = client.get("/stats/agreements").json()
    assert overview["total"] >= 1
    assert any(item["category"] == "КП" for item in overview["categories"])
    assert client.get("/audit").status_code == 200


def test_astservice_webhook_starts_pipeline(api: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """The Asterisk/Linphone webhook creates a client, a call, and queues ASR."""
    import io
    import uuid

    from app.api import worker

    submitted: list[int] = []
    monkeypatch.setattr(worker, "submit_call", lambda call_id: submitted.append(call_id))

    audio = b"RIFF" + uuid.uuid4().bytes * 40
    meta = (
        "{\"call_id\": \"1731000000000000001\", \"caller\": \"11111\", "
        "\"callee\": \"11119\", \"dial_status\": \"ANSWER\", "
        "\"answered_seconds\": \"42\", \"finished_at\": 1760101353, "
        "\"files\": {\"stereo\": \"/audio_records/x_stereo.wav\"}}"
    )
    client = api["client"]
    response = client.post(
        "/api/v1/process-audio",
        files={
            "metadata": (None, meta),
            "stereo": ("20261010-142233_stereo.wav", io.BytesIO(audio), "audio/wav"),
            "mixed": ("20261010-142233_mix.wav", io.BytesIO(b"RIFFmix"), "audio/wav"),
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["audio"] == "stereo"
    assert submitted == [data["call_id"]]

    detail = client.get(f"/calls/{data['call_id']}").json()
    assert detail["channels"] == 2
    assert detail["duration_sec"] == 42
    card = client.get(f"/clients/{detail['client_id']}").json()
    assert card["name"] == "Неизвестный"
    assert card["phone"] == "11119"

    from pathlib import Path

    from app import secure

    path = Path(detail["audio_path"])
    assert path.is_file()
    assert secure.is_encrypted(path)

    audit = client.get("/audit").json()
    assert any(row["action"] == "open_call" for row in audit)

    # Повторный вебхук того же call_id не заводит второй звонок
    again = client.post(
        "/api/v1/process-audio",
        files={
            "metadata": (None, meta),
            "stereo": ("20261010-142233_stereo.wav", io.BytesIO(audio), "audio/wav"),
        },
    )
    assert again.json()["call_id"] == data["call_id"]
    assert submitted == [data["call_id"]]
