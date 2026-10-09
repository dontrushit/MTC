"""Live Ollama extraction on fixed test transcript."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import ollama
import pytest

from app.config import settings
from app.db.models import SpeakerRole, Utterance
from app.extraction.dates import resolve_due
from app.extraction.llm import extract
from app.extraction.verify import verify_agreements

TZ = ZoneInfo("Europe/Moscow")
CALL_START = datetime(2026, 10, 9, 10, 0, tzinfo=TZ)

FIXTURE_UTTERANCES: list[tuple[SpeakerRole, str]] = [
    (
        SpeakerRole.MANAGER,
        "Добрый день, компания МТС, меня зовут Анна. "
        "Мы обсуждали поставку оборудования для вашего офиса.",
    ),
    (
        SpeakerRole.CLIENT,
        "Да, Анна, мы готовы двигаться дальше, если условия нас устроят.",
    ),
    (
        SpeakerRole.MANAGER,
        "Отлично. Я подготовлю коммерческое предложение и вышлю его вам до пятницы.",
    ),
    (
        SpeakerRole.CLIENT,
        "Хорошо, мы со своей стороны оплатим 150 тысяч рублей до 20 числа.",
    ),
    (
        SpeakerRole.MANAGER,
        "Договорились, завтра в 11 перезвоню, чтобы уточнить детали доставки.",
    ),
    (
        SpeakerRole.CLIENT,
        "Спасибо, буду ждать звонка и коммерческое предложение.",
    ),
]


def _ollama_available() -> bool:
    try:
        client = ollama.Client(host=settings.OLLAMA_URL)
        client.list()
        return True
    except (ConnectionError, OSError, ollama.ResponseError):
        return False


def _model_present(name: str) -> bool:
    try:
        client = ollama.Client(host=settings.OLLAMA_URL)
        models = client.list().get("models", [])
        for m in models:
            model_name = m.get("model") or m.get("name") or ""
            if model_name.split(":")[0] == name.split(":")[0] and name in model_name:
                return True
            if model_name == name:
                return True
        names = [m.get("model", m.get("name", "")) for m in models]
        return any(name in n or n.startswith(name.split(":")[0]) for n in names)
    except (ConnectionError, OSError, ollama.ResponseError):
        return False


@pytest.mark.slow
def test_live_extract_three_agreements(monkeypatch: pytest.MonkeyPatch) -> None:
    if not _ollama_available():
        pytest.skip("Ollama is not reachable")
    if not _model_present(settings.OLLAMA_MODEL):
        pytest.skip(f"Model {settings.OLLAMA_MODEL} not installed")

    utterances = [
        Utterance(
            call_id=0,
            speaker=sp,
            start_sec=float(i),
            end_sec=float(i) + 1,
            text=text,
        )
        for i, (sp, text) in enumerate(FIXTURE_UTTERANCES)
    ]

    result = extract(utterances, CALL_START)
    verified = verify_agreements(utterances, result.agreements)
    assert len(verified) == 3

    by_resp: dict[str, list] = {"manager": [], "client": []}
    for ag in verified:
        by_resp[ag.responsible].append(ag)

    assert len(by_resp["manager"]) == 2
    assert len(by_resp["client"]) == 1

    kp = next(a for a in verified if "коммер" in a.action.lower() or "кп" in a.action.lower())
    assert kp.responsible == "manager"
    assert resolve_due(kp.due_text, CALL_START, TZ) == datetime(2026, 10, 16).date()

    pay = by_resp["client"][0]
    assert "150000" in (pay.amount or "")
    assert resolve_due(pay.due_text, CALL_START, TZ) == datetime(2026, 10, 20).date()

    recall = next(a for a in by_resp["manager"] if "перезв" in a.action.lower())
    assert resolve_due(recall.due_text, CALL_START, TZ) == datetime(2026, 10, 10).date()
