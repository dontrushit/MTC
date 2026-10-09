"""Pydantic request and response schemas, separate from the ORM."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import AgreementResponsible, AgreementStatus, CallStatus, SpeakerRole


class OrmOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ClientIn(BaseModel):
    name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    phone: str = Field(min_length=1)


class ClientOut(OrmOut):
    id: int
    name: str
    last_name: str
    phone: str
    created_at: datetime


class ManagerIn(BaseModel):
    name: str = Field(min_length=1)
    telegram_chat_id: str | None = None
    is_supervisor: bool = False


class ManagerOut(OrmOut):
    id: int
    name: str
    telegram_chat_id: str | None
    is_supervisor: bool


class CallOut(OrmOut):
    id: int
    client_id: int
    manager_id: int
    audio_path: str
    started_at: datetime
    duration_sec: int
    channels: int
    status: CallStatus
    error_message: str | None
    report_topic: str = ""
    report_summary: str = ""
    report_json: str = "{}"


class UtteranceOut(OrmOut):
    id: int
    speaker: SpeakerRole
    start_sec: float
    end_sec: float
    text: str


class AgreementOut(OrmOut):
    id: int
    call_id: int
    client_id: int
    action: str
    responsible: AgreementResponsible
    due_date: date | None
    due_text: str
    amount: str | None
    conditions: str | None
    quote: str
    status: AgreementStatus
    created_at: datetime
    updated_at: datetime


class CallDetail(CallOut):
    utterances: list[UtteranceOut]
    agreements: list[AgreementOut]


class ClientDetail(ClientOut):
    calls: list[CallOut]
    agreements: list[AgreementOut]


class AgreementPatch(BaseModel):
    status: AgreementStatus | None = None
    due_date: date | None = None
    action: str | None = None
    conditions: str | None = None


class ManagerStats(BaseModel):
    manager_id: int
    name: str
    open: int
    overdue: int
    done: int
    done_on_time: float | None = Field(
        description="Percent of done agreements completed on or before the due date. "
        "Null when the manager has no done agreements."
    )
