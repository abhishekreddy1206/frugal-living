"""
Tracking module — money saved, food waste reduced, streaks, badges.

The "saved $X this month" headline lives here. Money tracking spans tiers
(Tier A: groceries, Tier S: bills negotiated, Tier B: shared goods received).
Streaks reward daily/weekly engagement.

All tables live in the `tracking` schema.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.core import TimestampMixin

# ---------- Budgets ----------

class Budget(Base, TimestampMixin):
    """Household budget per category per month. Used by savings calc + alerts."""
    __tablename__ = "budgets"
    __table_args__ = (
        Index("idx_budgets_household_month", "household_id", "month_start", unique=False),
        {"schema": "tracking"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    # groceries | dining_out | utilities | medical | other
    month_start: Mapped[date] = mapped_column(Date, nullable=False)
    target_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


# ---------- Spend log ----------

class SpendEntry(Base, TimestampMixin):
    """A single spend event. Receipt-import populates these; manual entry also writes here."""
    __tablename__ = "spend_entries"
    __table_args__ = (
        Index("idx_spend_household_date", "household_id", "spent_on"),
        {"schema": "tracking"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # groceries | dining_out | utilities | medical | other
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    spent_on: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    source: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    # manual | receipt | imported | inferred
    source_entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


# ---------- Savings events (the "you saved $X" hook) ----------

class SavingsEvent(Base, TimestampMixin):
    """
    Every time the app helps the household save money, log it here.
    Powers the dashboard headline.
    """
    __tablename__ = "savings_events"
    __table_args__ = (
        Index("idx_savings_household_date", "household_id", "occurred_on"),
        Index("idx_savings_kind", "kind"),
        {"schema": "tracking"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    # pantry_stretched | recipe_substituted | waste_avoided | bill_negotiated | swap_received | coupon_applied
    amount_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    source_entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # pantry_item | meal_plan | bill | swap | etc.
    source_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


# ---------- Streaks ----------

class Streak(Base, TimestampMixin):
    """Household streaks — cooked-from-pantry, zero-waste week, under-budget month."""
    __tablename__ = "streaks"
    __table_args__ = (
        Index("idx_streaks_household_kind", "household_id", "kind", unique=True),
        {"schema": "tracking"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    # cooked_from_pantry | zero_waste_week | under_budget_month | meal_planned_week
    current_length: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    longest_length: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_event_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


# ---------- Badges ----------

class BadgeDefinition(Base, TimestampMixin):
    """Catalog of badges that can be earned. Seeded once."""
    __tablename__ = "badge_definitions"
    __table_args__ = {"schema": "tracking"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    criteria: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    # e.g. {"streak_kind": "cooked_from_pantry", "threshold": 7}
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class BadgeAward(Base, TimestampMixin):
    """A household earned a badge."""
    __tablename__ = "badge_awards"
    __table_args__ = (
        Index("idx_badge_awards_household", "household_id"),
        {"schema": "tracking"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False
    )
    badge_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tracking.badge_definitions.id"), nullable=False
    )
    awarded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
