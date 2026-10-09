"""Unit tests for Ollama extraction wrapper (mocked)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.db.models import SpeakerRole, Utterance
from app.extraction.llm import ExtractionError, extract


def _utterances() -> list[Utterance]:
    return [
        Utterance(
            call_id=1,
            speaker=SpeakerRole.MANAGER,
            start_sec=0.0,
            end_sec=1.0,
            text="Тест.",
        )
    ]


VALID_JSON = '{"agreements": []}'
INVALID_JSON = '{"agreements": [{"action": "x"}]}'


def test_extract_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_client = MagicMock()
    mock_client.chat.return_value = MagicMock(message=MagicMock(content=VALID_JSON))
    monkeypatch.setattr("app.extraction.llm.ollama.Client", lambda **_: mock_client)

    result = extract(_utterances(), datetime.now(UTC))
    assert result.agreements == []
    assert mock_client.chat.call_count == 1


def test_extract_invalid_json_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_client = MagicMock()
    mock_client.chat.side_effect = [
        MagicMock(message=MagicMock(content=INVALID_JSON)),
        MagicMock(message=MagicMock(content=VALID_JSON)),
    ]
    monkeypatch.setattr("app.extraction.llm.ollama.Client", lambda **_: mock_client)

    result = extract(_utterances(), datetime.now(UTC))
    assert result.agreements == []
    assert mock_client.chat.call_count == 2


def test_extract_primary_fails_uses_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_client = MagicMock()

    def chat(**kwargs: object) -> MagicMock:
        model = kwargs.get("model")
        if model == "primary-model":
            raise ConnectionError("down")
        return MagicMock(message=MagicMock(content=VALID_JSON))

    mock_client.chat.side_effect = chat
    monkeypatch.setattr("app.extraction.llm.ollama.Client", lambda **_: mock_client)
    monkeypatch.setattr("app.extraction.llm.settings.OLLAMA_MODEL", "primary-model")
    monkeypatch.setattr("app.extraction.llm.settings.OLLAMA_FALLBACK_MODEL", "fallback-model")

    result = extract(_utterances(), datetime.now(UTC))
    assert result.agreements == []


def test_extract_both_models_fail_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_client = MagicMock()
    mock_client.chat.side_effect = ConnectionError("down")
    monkeypatch.setattr("app.extraction.llm.ollama.Client", lambda **_: mock_client)

    with pytest.raises(ExtractionError):
        extract(_utterances(), datetime.now(UTC))


def test_try_parse_validation() -> None:
    with pytest.raises(ValidationError):
        from app.extraction.llm import _try_parse

        _try_parse(INVALID_JSON)
