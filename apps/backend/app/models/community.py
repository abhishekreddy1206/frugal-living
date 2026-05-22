"""
Community tier — Tier B. Phase 1: a single-household inventory of durable
possessions. All tables live in the `community` schema.
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.core import TimestampMixin


class CommunityItem(Base, TimestampMixin):
    """A durable possession a household owns — game, tool, book, gear.

    Per-unit: one row is one thing. `quantity` covers genuinely fungible bulk
    (e.g. "8 folding chairs") without forcing eight rows.
    """

    __tablename__ = "items"
    __table_args__ = (
        Index("idx_items_household_category", "household_id", "category"),
        {"schema": "community"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="other", nullable=False)
    # tools | games | books | kitchen | outdoor | electronics | furniture | kids | sports | other
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    condition: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # new | like_new | good | fair | poor
    estimated_value_usd: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    location: Mapped[str | None] = mapped_column(String(120), nullable=True)
    acquired_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    # manual | photo_capture | chat
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
