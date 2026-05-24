"""
Community tier — Tier B. Phase 1: a single-household inventory of durable
possessions. All tables live in the `community` schema.
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
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
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


class Community(Base, TimestampMixin):
    """A joinable group of users (a building, neighborhood, friend circle, etc.)."""

    __tablename__ = "communities"
    __table_args__ = (
        Index("idx_communities_slug", "slug"),
        {"schema": "community"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    # ^[a-z0-9-]{2,80}$ — enforced at the schema layer; URL-safe handle.
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=False
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class CommunityMember(Base):
    """A user's current membership in a community. Leaving the community deletes
    the row; the historical record lives in `community_join_requests`.

    Deliberate deviation from Rule 4 (no `TimestampMixin` / `deleted_at`): same
    infra-table rationale as `core.events` / `core.audit_log` / `core.sessions`.
    """

    __tablename__ = "community_members"
    __table_args__ = (
        UniqueConstraint("community_id", "user_id", name="uq_community_members_unique"),
        Index("idx_community_members_user", "user_id"),
        {"schema": "community"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    community_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("community.communities.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), default="member", nullable=False)
    # owner | member
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class CommunityJoinRequest(Base):
    """Pending / decided join request. Partial unique index enforces at most one
    `pending` row per (community, user)."""

    __tablename__ = "community_join_requests"
    __table_args__ = (
        Index(
            "ux_pending_per_user_per_community",
            "community_id",
            "user_id",
            unique=True,
            postgresql_where="status = 'pending'",
        ),
        Index("idx_join_requests_community_status", "community_id", "status"),
        {"schema": "community"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    community_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("community.communities.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    # pending | approved | declined | withdrawn
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=True
    )
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class Listing(Base, TimestampMixin):
    """A household's public projection of an inventory item — visible in selected
    communities and/or within an opt-in geographic radius. One active listing per
    item enforced by a partial unique index."""

    __tablename__ = "listings"
    __table_args__ = (
        Index(
            "ux_one_active_listing_per_item",
            "item_id",
            unique=True,
            postgresql_where="deleted_at IS NULL AND availability_status != 'removed'",
        ),
        Index("idx_listings_item", "item_id"),
        {"schema": "community"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("community.items.id"), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=False
    )
    allowed_exchange_types: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, nullable=False
    )
    # subset of {borrow, swap, gift}, length >= 1
    quantity_available: Mapped[int] = mapped_column(Integer, nullable=False)
    share_in_radius: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    share_radius_miles: Mapped[int | None] = mapped_column(Integer, nullable=True)
    availability_status: Mapped[str] = mapped_column(String(16), default="available", nullable=False)
    # available | paused | removed
    description_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class ListingCommunity(Base):
    """Many-to-many: the explicit community picks for a listing. Used as a filter
    on top of the read-time membership check in the visibility helper."""

    __tablename__ = "listing_communities"
    __table_args__ = (
        PrimaryKeyConstraint("listing_id", "community_id"),
        Index("idx_listing_communities_community", "community_id"),
        {"schema": "community"},
    )

    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("community.listings.id"), nullable=False
    )
    community_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("community.communities.id"), nullable=False
    )
    added_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
