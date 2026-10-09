"""Pydantic schemas for LLM agreement extraction."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ExtractedAgreement(BaseModel):
    action: str = Field(description="Кратко: глагол + объект")
    responsible: Literal["manager", "client"]
    due_text: str | None = Field(
        default=None,
        description="Формулировка срока дословно из речи",
    )
    amount: str | None = Field(
        default=None,
        description="Сумма в формате «150000 RUB»",
    )
    conditions: str | None = None
    quote: str = Field(description="Дословная цитата из одной реплики")
    utterance_index: int = Field(ge=0)


class ExtractionResult(BaseModel):
    agreements: list[ExtractedAgreement] = Field(default_factory=list)
