"""SQLAlchemy 2.x ORM models for clients, calls, utterances, and agreements."""

from __future__ import annotations

import enum
from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class CallStatus(enum.StrEnum):
    NEW = "new"
    PROCESSING = "processing"
    TRANSCRIBED = "transcribed"
    EXTRACTED = "extracted"
    ERROR = "error"


class SpeakerRole(enum.StrEnum):
    MANAGER = "manager"
    CLIENT = "client"


class AgreementResponsible(enum.StrEnum):
    MANAGER = "manager"
    CLIENT = "client"


class AgreementStatus(enum.StrEnum):
    OPEN = "open"
    DONE = "done"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", server_default=""
    )
    phone: Mapped[str] = mapped_column(String(64), nullable=False)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    calls: Mapped[list[Call]] = relationship(back_populates="client")
    agreements: Mapped[list[Agreement]] = relationship(back_populates="client")


class Manager(Base):
    __tablename__ = "managers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_supervisor: Mapped[bool] = mapped_column(default=False, nullable=False)

    calls: Mapped[list[Call]] = relationship(back_populates="manager")


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False)
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"), nullable=False)
    audio_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    channels: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[CallStatus] = mapped_column(
        Enum(CallStatus, native_enum=False, length=32),
        default=CallStatus.NEW,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_topic: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    report_summary: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    report_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default="{}"
    )

    client: Mapped[Client] = relationship(back_populates="calls")
    manager: Mapped[Manager] = relationship(back_populates="calls")
    utterances: Mapped[list[Utterance]] = relationship(back_populates="call")
    agreements: Mapped[list[Agreement]] = relationship(back_populates="call")


class Utterance(Base):
    __tablename__ = "utterances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id"), nullable=False)
    speaker: Mapped[SpeakerRole] = mapped_column(
        Enum(SpeakerRole, native_enum=False, length=16), nullable=False
    )
    start_sec: Mapped[float] = mapped_column(nullable=False)
    end_sec: Mapped[float] = mapped_column(nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    call: Mapped[Call] = relationship(back_populates="utterances")


class Agreement(Base):
    __tablename__ = "agreements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("calls.id"), nullable=False)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    responsible: Mapped[AgreementResponsible] = mapped_column(
        Enum(AgreementResponsible, native_enum=False, length=16), nullable=False
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_text: Mapped[str] = mapped_column(String(512), nullable=False)
    amount: Mapped[str | None] = mapped_column(String(64), nullable=True)
    conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[AgreementStatus] = mapped_column(
        Enum(AgreementStatus, native_enum=False, length=16),
        default=AgreementStatus.OPEN,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    call: Mapped[Call] = relationship(back_populates="agreements")
    client: Mapped[Client] = relationship(back_populates="agreements")
