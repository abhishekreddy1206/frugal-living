"""
AI module — Claude conversations, voice sessions, daily briefings.

Cross-cutting across all tiers. A conversation can be scoped to a household, a
specific tier (food/bills/community), or unscoped (general chat). All tables
live in the `ai` schema.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import (
    String, DateTime, ForeignKey, Integer, Text, Index, Boolean, Numeric, func
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.core import TimestampMixin


class Conversation(Base, TimestampMixin):
    """A Claude chat session. Persistent across page loads."""
    __tablename__ = "conversations"
    __table_args__ = (
        Index("idx_conversations_household_recent", "household_id", "updated_at"),
        {"schema": "ai"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=True
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    scope: Mapped[str] = mapped_column(String(32), default="general", nullable=False)
    # general | food | bills | community | briefing | voice
    surface: Mapped[str] = mapped_column(String(32), default="sidebar", nullable=False)
    # sidebar | inline | voice | briefing
    model: Mapped[str] = mapped_column(String(64), default="claude-sonnet-4-6", nullable=False)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    messages: Mapped[list[Message]] = relationship(back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_messages_conversation_created", "conversation_id", "created_at"),
        {"schema": "ai"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # user | assistant | system | tool
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Tool calls / tool results / structured outputs go here
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class VoiceSession(Base, TimestampMixin):
    """A 'hey Hearth' voice session — Whisper transcript + Claude turns + TTS."""
    __tablename__ = "voice_sessions"
    __table_args__ = {"schema": "ai"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai.conversations.id"), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    wake_phrase: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class Briefing(Base, TimestampMixin):
    """Daily proactive briefing — what's expiring, what to cook, dollars saved."""
    __tablename__ = "briefings"
    __table_args__ = (
        Index("idx_briefings_household_date", "household_id", "for_date", unique=True),
        {"schema": "ai"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False
    )
    for_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    headline: Mapped[str | None] = mapped_column(String(300), nullable=True)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    delivered_via: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    # in_app | email | push
    was_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
