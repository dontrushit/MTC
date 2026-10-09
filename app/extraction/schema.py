"""Pydantic schemas for LLM agreement extraction."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ExtractedAgreement(BaseModel):
    action: str = Field(
        description=(
            "Название: инфинитив и предмет, без срока и без суммы. "
            "Срок и сумма — в своих полях."
        ),
    )
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
    topic: str = Field(default="", description="Тема звонка, 3–6 слов")
    brief: str = Field(
        default="",
        description="1–2 предложения контекста. Не пересказывай договорённости",
    )
    unresolved: str = Field(
        default="",
        description="Что не решили, одним предложением. Пусто, если всё ясно",
    )
    agreements: list[ExtractedAgreement] = Field(default_factory=list)
