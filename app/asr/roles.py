"""Decide which transcribed voice is the employee and which is the customer.

Channel split only guesses: the first speaker, or the left channel, starts as the
manager. A self-introduction such as «работник МТС» overrides that guess. Otherwise
the local model reads the dialog and keeps the guess when the roles are unclear.
"""

from __future__ import annotations

import logging
import re
from typing import Literal

import ollama
from pydantic import BaseModel, ValidationError

from app.asr.transcribe import Segment
from app.config import settings
from app.db.models import SpeakerRole

logger = logging.getLogger(__name__)

_OLLAMA_TIMEOUT = 90

_STRONG_EMPLOYEE = (
    r"работни\w*\s+мтс",
    r"сотрудни\w*\s+мтс",
    r"оператор\w*\s+мтс",
    r"\bя\s+из\s+мтс\b",
    r"\bэто\s+мтс\b",
    r"мтс[,.]?\s+меня\s+зовут",
    r"компания\s+мтс[,.]?\s+меня\s+зовут",
)

_SYSTEM = """\
Ты определяешь, кто в телефонном разговоре сотрудник компании, а кто клиент.

A и B — это два разных голоса, а не роли. Сотрудник представляется, помогает, \
оформляет услугу, называет компанию. Клиент обращается с просьбой или вопросом.

Верни JSON {"manager": "a"}, {"manager": "b"} или {"manager": "unknown"}.
unknown — если по репликам нельзя уверенно понять, кто сотрудник.
"""


class RoleDecision(BaseModel):
    manager: Literal["a", "b", "unknown"]


def resolve_roles(segments: list[Segment]) -> list[Segment]:
    """Return the dialog with the employee labeled manager and the other person client."""
    if not segments:
        return segments
    spoken = {seg.speaker for seg in segments if seg.text.strip()}
    if spoken != {SpeakerRole.MANAGER, SpeakerRole.CLIENT}:
        return segments

    employee = _employee_by_phrase(segments)
    if employee is None:
        employee = _employee_by_model(segments)
    if employee == SpeakerRole.CLIENT:
        logger.info("Speaker roles swapped: the employee was labeled as the client")
        return [_flipped(seg) for seg in segments]
    return segments


def _employee_by_phrase(segments: list[Segment]) -> SpeakerRole | None:
    """The voice that says it works at MTS. None when both do, or neither does."""
    hits = {SpeakerRole.MANAGER: False, SpeakerRole.CLIENT: False}
    for seg in segments:
        if _is_employee_phrase(seg.text):
            hits[seg.speaker] = True
    if hits[SpeakerRole.MANAGER] and not hits[SpeakerRole.CLIENT]:
        return SpeakerRole.MANAGER
    if hits[SpeakerRole.CLIENT] and not hits[SpeakerRole.MANAGER]:
        return SpeakerRole.CLIENT
    return None


def _is_employee_phrase(text: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    normalized = re.sub(r"\s+", " ", normalized)
    return any(re.search(pattern, normalized) for pattern in _STRONG_EMPLOYEE)


def _employee_by_model(segments: list[Segment]) -> SpeakerRole | None:
    """Ask the local model which provisional voice is the employee."""
    lines = []
    for seg in segments:
        mark = "A" if seg.speaker == SpeakerRole.MANAGER else "B"
        lines.append(f"{mark}: {seg.text.strip()}")
    transcript = "\n".join(lines)
    if len(transcript) > 6000:
        transcript = transcript[:6000]
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": transcript},
    ]
    client = ollama.Client(host=settings.OLLAMA_URL, timeout=_OLLAMA_TIMEOUT)
    for model in (settings.OLLAMA_MODEL, settings.OLLAMA_FALLBACK_MODEL):
        try:
            decision = _ask(client, model, messages)
        except Exception as exc:
            logger.warning("Role check failed (model=%s): %s", model, exc)
            continue
        if decision == "a":
            return SpeakerRole.MANAGER
        if decision == "b":
            return SpeakerRole.CLIENT
        return None
    return None


def _ask(client: ollama.Client, model: str, messages: list[dict[str, str]]) -> str:
    response = client.chat(
        model=model,
        messages=messages,
        format=RoleDecision.model_json_schema(),
        options={"temperature": 0, "num_ctx": 4096},
    )
    content = response.message.content or ""
    try:
        return RoleDecision.model_validate_json(content).manager
    except ValidationError as exc:
        raise ValueError(content[:200]) from exc


def _flipped(seg: Segment) -> Segment:
    other = {
        SpeakerRole.MANAGER: SpeakerRole.CLIENT,
        SpeakerRole.CLIENT: SpeakerRole.MANAGER,
    }
    return Segment(speaker=other[seg.speaker], start=seg.start, end=seg.end, text=seg.text)
