"""Ollama-backed structured agreement extraction."""

from __future__ import annotations

import logging
from datetime import datetime

import httpx
import ollama
from pydantic import ValidationError

from app.config import settings
from app.db.models import Utterance
from app.extraction.prompt import build_messages
from app.extraction.schema import ExtractionResult

logger = logging.getLogger(__name__)

_OLLAMA_TIMEOUT = 180

_NETWORK_ERRORS = (
    ollama.ResponseError,
    ConnectionError,
    TimeoutError,
    httpx.TimeoutException,
    httpx.ConnectError,
)


class ExtractionError(Exception):
    """LLM extraction failed after retries and fallback."""


def _chat_extract(client: ollama.Client, model: str, messages: list[dict[str, str]]) -> str:
    response = client.chat(
        model=model,
        messages=messages,
        format=ExtractionResult.model_json_schema(),
        options={"temperature": 0, "num_ctx": 16384},
    )
    content = response.message.content
    if not content:
        msg = "Empty response from Ollama"
        raise ExtractionError(msg)
    return content


def _try_parse(raw: str) -> ExtractionResult:
    return ExtractionResult.model_validate_json(raw)


def extract(utterances: list[Utterance], call_started_at: datetime) -> ExtractionResult:
    """Extract agreements from utterances via Ollama with validation retry and fallback."""
    messages = build_messages(utterances, call_started_at)
    client = ollama.Client(host=settings.OLLAMA_URL, timeout=_OLLAMA_TIMEOUT)

    def run_model(model: str, *, allow_retry: bool) -> ExtractionResult:
        last_err: Exception | None = None
        attempts = 2 if allow_retry else 1
        for attempt in range(attempts):
            try:
                raw = _chat_extract(client, model, messages)
                return _try_parse(raw)
            except ValidationError as exc:
                last_err = exc
                logger.warning(
                    "Extraction JSON validation failed (model=%s, attempt=%s): %s",
                    model,
                    attempt + 1,
                    exc,
                )
            except _NETWORK_ERRORS as exc:
                last_err = exc
                logger.warning("Ollama request failed (model=%s): %s", model, exc)
                break
            except ExtractionError as exc:
                last_err = exc
                break
        if last_err:
            raise last_err
        msg = f"Extraction failed for model {model}"
        raise ExtractionError(msg)

    try:
        return run_model(settings.OLLAMA_MODEL, allow_retry=True)
    except Exception as primary_err:
        logger.warning(
            "Primary model %s failed (%s), trying fallback %s",
            settings.OLLAMA_MODEL,
            primary_err,
            settings.OLLAMA_FALLBACK_MODEL,
        )
        try:
            return run_model(settings.OLLAMA_FALLBACK_MODEL, allow_retry=True)
        except Exception as fallback_err:
            msg = (
                f"Extraction failed: primary={primary_err!s}; "
                f"fallback={fallback_err!s}"
            )
            raise ExtractionError(msg) from fallback_err
