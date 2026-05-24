# Tier B Phase 2 — Community & Shareable Listings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-user communities (request-to-join + owner approval), household-owned shareable listings (one active per item, default-private radius), and a discovery feed gated by a single canonical visibility helper — so households browse each other's items without buying or transacting yet.

**Architecture:** Five new `community` schema tables (one migration, `0005`). All cross-household reads funnel through `services/community/visibility.py` whose query re-checks community membership at read time, filters on `users.is_active` + `communities.deleted_at`, and applies a bounding-box geo filter on lat/lng stored in `households.metadata_`. Item soft-delete cascades to listings; item-quantity changes reconcile listings' `quantity_available`. The auth-feature CSRF posture is inherited; Phase 2 adds no GET endpoints that mutate.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy 2.0 / Alembic / PostgreSQL (no new backend deps), Next.js 14 / TypeScript / Tailwind (no new frontend deps — browser geolocation is built-in). `uv` (backend), `pnpm` (frontend).

**Spec:** `docs/superpowers/specs/2026-05-24-tier-b-phase-2-community-listings-design.md`

All backend commands run from `apps/backend/`; all frontend commands from `apps/web/`. Postgres must be running. Implement in an isolated worktree.

---

### Task 1: Phase 2 models + migration `0005`

**Files:**
- Modify: `apps/backend/app/models/community.py`
- Create: `apps/backend/alembic/versions/0005_community_listings.py`
- Test: `apps/backend/tests/test_community_phase2_models.py`

- [ ] **Step 1: Add the five new models**

In `apps/backend/app/models/community.py`, append at the end of the file (after the existing `CommunityItem` class):

```python
from sqlalchemy import Boolean, PrimaryKeyConstraint, UniqueConstraint
# (Add Boolean, PrimaryKeyConstraint, UniqueConstraint to the existing sqlalchemy imports at the top.)


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
```

- [ ] **Step 2: Write the migration**

Create `apps/backend/alembic/versions/0005_community_listings.py`:

```python
"""community phase 2: communities, members, join_requests, listings, listing_communities

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-24

"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # community.communities
    op.create_table(
        "communities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["core.users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
        schema="community",
    )
    op.create_index("idx_communities_slug", "communities", ["slug"], schema="community")

    # community.community_members
    op.create_table(
        "community_members",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("community_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["community_id"], ["community.communities.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["core.users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("community_id", "user_id", name="uq_community_members_unique"),
        schema="community",
    )
    op.create_index("idx_community_members_user", "community_members", ["user_id"], schema="community")

    # community.community_join_requests
    op.create_table(
        "community_join_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("community_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_user_id", sa.UUID(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["community_id"], ["community.communities.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["core.users.id"]),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["core.users.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="community",
    )
    op.create_index(
        "ux_pending_per_user_per_community",
        "community_join_requests",
        ["community_id", "user_id"],
        unique=True,
        schema="community",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "idx_join_requests_community_status",
        "community_join_requests",
        ["community_id", "status"],
        schema="community",
    )

    # community.listings
    op.create_table(
        "listings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column("allowed_exchange_types", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("quantity_available", sa.Integer(), nullable=False),
        sa.Column("share_in_radius", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("share_radius_miles", sa.Integer(), nullable=True),
        sa.Column("availability_status", sa.String(length=16), nullable=False),
        sa.Column("description_override", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["item_id"], ["community.items.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["core.users.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="community",
    )
    op.create_index(
        "ux_one_active_listing_per_item",
        "listings",
        ["item_id"],
        unique=True,
        schema="community",
        postgresql_where=sa.text("deleted_at IS NULL AND availability_status != 'removed'"),
    )
    op.create_index("idx_listings_item", "listings", ["item_id"], schema="community")

    # community.listing_communities
    op.create_table(
        "listing_communities",
        sa.Column("listing_id", sa.UUID(), nullable=False),
        sa.Column("community_id", sa.UUID(), nullable=False),
        sa.Column("added_by_user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["listing_id"], ["community.listings.id"]),
        sa.ForeignKeyConstraint(["community_id"], ["community.communities.id"]),
        sa.ForeignKeyConstraint(["added_by_user_id"], ["core.users.id"]),
        sa.PrimaryKeyConstraint("listing_id", "community_id"),
        schema="community",
    )
    op.create_index(
        "idx_listing_communities_community",
        "listing_communities",
        ["community_id"],
        schema="community",
    )


def downgrade() -> None:
    op.drop_index("idx_listing_communities_community", table_name="listing_communities", schema="community")
    op.drop_table("listing_communities", schema="community")
    op.drop_index("idx_listings_item", table_name="listings", schema="community")
    op.drop_index("ux_one_active_listing_per_item", table_name="listings", schema="community")
    op.drop_table("listings", schema="community")
    op.drop_index("idx_join_requests_community_status", table_name="community_join_requests", schema="community")
    op.drop_index("ux_pending_per_user_per_community", table_name="community_join_requests", schema="community")
    op.drop_table("community_join_requests", schema="community")
    op.drop_index("idx_community_members_user", table_name="community_members", schema="community")
    op.drop_table("community_members", schema="community")
    op.drop_index("idx_communities_slug", table_name="communities", schema="community")
    op.drop_table("communities", schema="community")
```

- [ ] **Step 3: Apply the migration**

Run: `uv run alembic upgrade head`
Expected: ends with `Running upgrade 0004 -> 0005, community phase 2: communities, members, join_requests, listings, listing_communities`.

- [ ] **Step 4: Write the model roundtrip test**

Create `apps/backend/tests/test_community_phase2_models.py`:

```python
"""Model roundtrip tests for the Phase 2 community tables."""
from __future__ import annotations

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.community import (
    Community,
    CommunityItem,
    CommunityJoinRequest,
    CommunityMember,
    Listing,
    ListingCommunity,
)


def test_community_roundtrip(db):
    c = Community(
        slug="park-slope-tools",
        name="Park Slope Tools",
        description="A neighborhood tool library",
        created_by_user_id=DEV_USER_ID,
    )
    db.add(c)
    db.flush()
    fetched = db.get(Community, c.id)
    assert fetched is not None
    assert fetched.slug == "park-slope-tools"
    assert fetched.metadata_ == {}
    assert fetched.deleted_at is None


def test_community_member_unique(db):
    c = Community(slug="t1", name="t1", created_by_user_id=DEV_USER_ID)
    db.add(c); db.flush()
    db.add(CommunityMember(community_id=c.id, user_id=DEV_USER_ID, role="owner"))
    db.flush()
    # Same (community, user) again should fail.
    db.add(CommunityMember(community_id=c.id, user_id=DEV_USER_ID, role="member"))
    import pytest
    with pytest.raises(Exception):
        db.flush()


def test_join_request_partial_unique_pending(db):
    c = Community(slug="t2", name="t2", created_by_user_id=DEV_USER_ID)
    db.add(c); db.flush()
    db.add(CommunityJoinRequest(community_id=c.id, user_id=DEV_USER_ID, status="pending"))
    db.flush()
    # Second pending for same (community, user) should fail.
    db.add(CommunityJoinRequest(community_id=c.id, user_id=DEV_USER_ID, status="pending"))
    import pytest
    with pytest.raises(Exception):
        db.flush()


def test_listing_one_active_per_item(db):
    item = CommunityItem(household_id=DEV_HOUSEHOLD_ID, created_by_user_id=DEV_USER_ID, name="Drill")
    db.add(item); db.flush()
    db.add(Listing(
        item_id=item.id, created_by_user_id=DEV_USER_ID,
        allowed_exchange_types=["borrow"], quantity_available=1,
        availability_status="available",
    ))
    db.flush()
    # Second active listing for the same item should fail (partial unique index).
    db.add(Listing(
        item_id=item.id, created_by_user_id=DEV_USER_ID,
        allowed_exchange_types=["gift"], quantity_available=1,
        availability_status="available",
    ))
    import pytest
    with pytest.raises(Exception):
        db.flush()


def test_listing_community_join_roundtrip(db):
    item = CommunityItem(household_id=DEV_HOUSEHOLD_ID, created_by_user_id=DEV_USER_ID, name="Tent")
    c = Community(slug="t3", name="t3", created_by_user_id=DEV_USER_ID)
    db.add(item); db.add(c); db.flush()
    listing = Listing(
        item_id=item.id, created_by_user_id=DEV_USER_ID,
        allowed_exchange_types=["borrow"], quantity_available=1,
        availability_status="available",
    )
    db.add(listing); db.flush()
    db.add(ListingCommunity(listing_id=listing.id, community_id=c.id, added_by_user_id=DEV_USER_ID))
    db.flush()
```

- [ ] **Step 5: Update conftest cleanup**

In `apps/backend/tests/conftest.py`, update the imports to include the new models and the `_clean_household_data` fixture to clean them. After the existing `from app.models.community import CommunityItem` line, add:

```python
from app.models.community import (
    Community,
    CommunityJoinRequest,
    CommunityMember,
    Listing,
    ListingCommunity,
)
```

Inside `_clean_household_data`, add these delete statements BEFORE the existing `db_.query(CommunityItem)...` line (since listings reference items via FK):

```python
        # Phase 2: listing_communities -> listings -> (then items below)
        db_.query(ListingCommunity).delete()
        db_.query(Listing).delete()
        # Phase 2: community memberships + join requests + communities
        db_.query(CommunityMember).delete()
        db_.query(CommunityJoinRequest).delete()
        db_.query(Community).delete()
```

(The bulk deletes are safe — `_clean_household_data` runs before every test, and Phase 2 tables aren't household-scoped at the row level.)

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_community_phase2_models.py -v && uv run pytest -q`
Expected: 5 new tests pass; full suite passes (the existing 243 + 5 = 248 passed, 1 skipped).

- [ ] **Step 7: Commit**

```bash
git add apps/backend/app/models/community.py \
  apps/backend/alembic/versions/0005_community_listings.py \
  apps/backend/tests/conftest.py \
  apps/backend/tests/test_community_phase2_models.py
git commit -m "feat(community): phase 2 models + migration 0005 (communities, members, join_requests, listings, listing_communities)"
```

---

### Task 2: Phase 2 Pydantic schemas

**Files:**
- Modify: `apps/backend/app/schemas/community.py`
- Test: `apps/backend/tests/test_community_phase2_schemas.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_community_phase2_schemas.py`:

```python
"""Validation tests for Phase 2 schemas."""
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.community import (
    CommunityCreate,
    JoinRequestDecideRequest,
    ListingCreate,
    ListingUpdate,
)


def test_community_create_rejects_bad_slug():
    with pytest.raises(ValidationError):
        CommunityCreate(slug="Has Spaces", name="x")
    with pytest.raises(ValidationError):
        CommunityCreate(slug="a", name="x")  # too short
    with pytest.raises(ValidationError):
        CommunityCreate(slug="UPPER", name="x")  # uppercase


def test_community_create_accepts_valid_slug():
    c = CommunityCreate(slug="park-slope-tools", name="Park Slope Tools")
    assert c.slug == "park-slope-tools"


def test_listing_create_requires_at_least_one_exchange_type():
    with pytest.raises(ValidationError):
        ListingCreate(item_id=uuid.uuid4(), allowed_exchange_types=[], quantity_available=1)


def test_listing_create_rejects_unknown_exchange_type():
    with pytest.raises(ValidationError):
        ListingCreate(
            item_id=uuid.uuid4(),
            allowed_exchange_types=["sell"],  # not allowed
            quantity_available=1,
        )


def test_listing_create_accepts_borrow_swap_gift():
    lc = ListingCreate(
        item_id=uuid.uuid4(),
        allowed_exchange_types=["borrow", "gift"],
        quantity_available=2,
        community_ids=[uuid.uuid4()],
        share_in_radius=True,
    )
    assert lc.quantity_available == 2


def test_listing_update_all_optional():
    ListingUpdate()  # empty patch is valid


def test_decide_request_note_optional():
    JoinRequestDecideRequest()  # no note
    JoinRequestDecideRequest(note="not yet")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_community_phase2_schemas.py -v`
Expected: FAIL with `ImportError` — the new schemas don't exist yet.

- [ ] **Step 3: Append the Phase 2 schemas**

In `apps/backend/app/schemas/community.py`, append at the end:

```python
# ---------- Phase 2: communities & listings ----------

import uuid as _uuid  # noqa: E402 — kept local to the Phase 2 block for clarity
from datetime import datetime as _datetime

_SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{1,79}$"

EXCHANGE_TYPES = ["borrow", "swap", "gift"]
_EXCHANGE_PATTERN = "^(" + "|".join(EXCHANGE_TYPES) + ")$"

AVAILABILITY_STATUSES = ["available", "paused", "removed"]
_AVAILABILITY_PATTERN = "^(" + "|".join(AVAILABILITY_STATUSES) + ")$"

COMMUNITY_ROLES = ["owner", "member"]
_ROLE_PATTERN = "^(" + "|".join(COMMUNITY_ROLES) + ")$"

JOIN_REQUEST_STATUSES = ["pending", "approved", "declined", "withdrawn"]


# ---- Communities ----

class CommunityCreate(BaseModel):
    slug: str = Field(..., pattern=_SLUG_PATTERN, min_length=2, max_length=80)
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class CommunityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class CommunityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: _uuid.UUID
    slug: str
    name: str
    description: str | None
    created_at: _datetime


class CommunityPreview(BaseModel):
    """Public-ish preview returned by GET /communities/{slug} — no member identities."""
    id: _uuid.UUID
    slug: str
    name: str
    description: str | None
    member_count: int
    your_membership_role: str | None  # null if not a member
    your_join_request_status: str | None  # null if no request


class CommunityMembershipRead(BaseModel):
    """Item in 'my communities' / 'community members' lists."""
    community: CommunityRead
    role: str
    joined_at: _datetime


class MyCommunitiesResponse(BaseModel):
    memberships: list[CommunityMembershipRead]


# ---- Join requests ----

class JoinRequestDecideRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class JoinRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: _uuid.UUID
    community_id: _uuid.UUID
    user_id: _uuid.UUID
    status: str
    requested_at: _datetime
    decided_at: _datetime | None
    decision_note: str | None


# ---- Listings ----

class ListingCreate(BaseModel):
    item_id: _uuid.UUID
    allowed_exchange_types: list[str] = Field(..., min_length=1)
    quantity_available: int = Field(..., ge=1)
    community_ids: list[_uuid.UUID] = Field(default_factory=list)
    share_in_radius: bool = False
    share_radius_miles: int | None = Field(default=None, ge=1, le=500)
    description_override: str | None = Field(default=None, max_length=2000)

    @field_validator("allowed_exchange_types")
    @classmethod
    def _validate_exchange_types(cls, v: list[str]) -> list[str]:
        bad = [x for x in v if x not in EXCHANGE_TYPES]
        if bad:
            raise ValueError(f"unknown exchange type(s): {bad}; allowed: {EXCHANGE_TYPES}")
        return v


class ListingUpdate(BaseModel):
    allowed_exchange_types: list[str] | None = None
    quantity_available: int | None = Field(default=None, ge=1)
    community_ids: list[_uuid.UUID] | None = None
    share_in_radius: bool | None = None
    share_radius_miles: int | None = Field(default=None, ge=1, le=500)
    description_override: str | None = Field(default=None, max_length=2000)
    availability_status: str | None = Field(default=None, pattern=_AVAILABILITY_PATTERN)

    @field_validator("allowed_exchange_types")
    @classmethod
    def _validate_exchange_types(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        bad = [x for x in v if x not in EXCHANGE_TYPES]
        if bad:
            raise ValueError(f"unknown exchange type(s): {bad}; allowed: {EXCHANGE_TYPES}")
        return v


class ListingItemSummary(BaseModel):
    """Item fields that appear in a listing/feed response — never exposes lat/lng."""
    id: _uuid.UUID
    name: str
    category: str
    tags: list[str]
    quantity: int
    condition: str | None
    estimated_value_usd: float | None
    photo_url: str | None
    notes: str | None


class ListingRead(BaseModel):
    """Detail view for a listing — for the owning household it includes everything;
    for visibility-gated callers it includes only what is safe to share."""
    id: _uuid.UUID
    item: ListingItemSummary
    allowed_exchange_types: list[str]
    quantity_available: int
    share_in_radius: bool
    share_radius_miles: int | None
    availability_status: str
    description_override: str | None
    community_ids: list[_uuid.UUID]  # the listing's picks (visible to anyone with access to the listing)
    created_at: _datetime


class FeedRow(BaseModel):
    """One row in the discovery feed. Excludes lat/lng — distance is rounded."""
    listing: ListingRead
    distance_miles: float | None  # set when matched via radius path; otherwise null
    matched_community_id: _uuid.UUID | None  # set when matched via community path; otherwise null


class FeedResponse(BaseModel):
    rows: list[FeedRow]
    next_cursor: str | None  # opaque pagination cursor; null when no more pages
```

Also add this import at the top of `apps/backend/app/schemas/community.py` (alongside the existing `from pydantic import …` line):

```python
from pydantic import BaseModel, ConfigDict, Field, field_validator
```

(If `field_validator` is not already in the existing import line, add it.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_community_phase2_schemas.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/schemas/community.py apps/backend/tests/test_community_phase2_schemas.py
git commit -m "feat(community): phase 2 Pydantic schemas for communities, join requests, listings"
```

---

### Task 3: `communities` service

**Files:**
- Create: `apps/backend/app/services/community/communities.py`
- Test: `apps/backend/tests/test_community_communities_service.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_community_communities_service.py`:

```python
"""Tests for the communities service."""
from __future__ import annotations

import pytest

from app.auth import DEV_USER_ID
from app.models.community import Community, CommunityMember
from app.models.core import AuditLog, Event, User
from app.services.community import communities as svc
from app.services.community.communities import (
    CommunityNotFound,
    CommunitySlugTaken,
    NotACommunityMember,
)


def _user(db):
    return db.get(User, DEV_USER_ID)


def test_create_community_makes_creator_owner(db):
    user = _user(db)
    c = svc.create_community(
        db, creator_user=user, slug="park-slope-tools", name="Park Slope Tools",
    )
    assert c.slug == "park-slope-tools"
    member = (
        db.query(CommunityMember)
        .filter_by(community_id=c.id, user_id=user.id)
        .one()
    )
    assert member.role == "owner"
    assert db.query(Event).filter_by(event_type="community.community.created").count() == 1
    assert db.query(AuditLog).filter_by(action="community.community.created").count() == 1


def test_create_community_rejects_duplicate_slug(db):
    user = _user(db)
    svc.create_community(db, creator_user=user, slug="dup", name="A")
    with pytest.raises(CommunitySlugTaken):
        svc.create_community(db, creator_user=user, slug="dup", name="B")


def test_get_by_slug_returns_none_when_missing(db):
    assert svc.get_community_by_slug(db, "nope") is None


def test_get_by_slug_excludes_soft_deleted(db):
    user = _user(db)
    c = svc.create_community(db, creator_user=user, slug="gone", name="Gone")
    svc.soft_delete_community(db, owner_user=user, community=c)
    assert svc.get_community_by_slug(db, "gone") is None


def test_soft_delete_requires_owner(db):
    user = _user(db)
    c = svc.create_community(db, creator_user=user, slug="o1", name="o1")
    # Demote ourselves to member so the owner-check fails.
    member = (
        db.query(CommunityMember)
        .filter_by(community_id=c.id, user_id=user.id).one()
    )
    member.role = "member"
    db.flush()
    with pytest.raises(NotACommunityMember):
        svc.soft_delete_community(db, owner_user=user, community=c)


def test_leave_community_removes_membership(db):
    user = _user(db)
    c = svc.create_community(db, creator_user=user, slug="l1", name="l1")
    # The owner can't leave the *only* owner row (409); demote to member-only first.
    member = db.query(CommunityMember).filter_by(community_id=c.id, user_id=user.id).one()
    member.role = "member"
    db.flush()
    svc.leave_community(db, user=user, community=c)
    assert (
        db.query(CommunityMember).filter_by(community_id=c.id, user_id=user.id).count() == 0
    )


def test_owner_cannot_leave_if_sole_owner(db):
    user = _user(db)
    c = svc.create_community(db, creator_user=user, slug="o2", name="o2")
    from app.services.community.communities import SoleOwnerCannotLeave
    with pytest.raises(SoleOwnerCannotLeave):
        svc.leave_community(db, user=user, community=c)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_community_communities_service.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create the service**

Create `apps/backend/app/services/community/communities.py`:

```python
"""Communities service — create / fetch / soft-delete / leave."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.community import Community, CommunityMember
from app.models.core import AuditLog, User
from app.services.events import emit_event


class CommunityNotFound(Exception):
    """Community id or slug not found (or soft-deleted)."""


class CommunitySlugTaken(Exception):
    """A community with that slug already exists."""


class NotACommunityMember(Exception):
    """User is not a member (or not an owner) of the community."""


class SoleOwnerCannotLeave(Exception):
    """Owner may not leave when they are the only owner — soft-delete instead."""


def _audit(db: Session, *, action: str, user_id, community_id, payload: dict | None = None) -> None:
    db.add(AuditLog(
        actor_user_id=user_id,
        action=action,
        target_type="community",
        target_id=community_id,
        payload=payload or {},
    ))


def get_community_by_slug(db: Session, slug: str) -> Community | None:
    return (
        db.query(Community)
        .filter(Community.slug == slug, Community.deleted_at.is_(None))
        .one_or_none()
    )


def get_community_or_404(db: Session, community_id: uuid.UUID) -> Community:
    c = db.get(Community, community_id)
    if c is None or c.deleted_at is not None:
        raise CommunityNotFound(str(community_id))
    return c


def _require_owner(db: Session, *, user: User, community: Community) -> CommunityMember:
    member = (
        db.query(CommunityMember)
        .filter_by(community_id=community.id, user_id=user.id)
        .one_or_none()
    )
    if member is None or member.role != "owner":
        raise NotACommunityMember(f"user {user.id} is not an owner of community {community.id}")
    return member


def create_community(
    db: Session, *, creator_user: User, slug: str, name: str, description: str | None = None,
) -> Community:
    """Create a community, add creator as owner, emit event + audit row."""
    c = Community(
        slug=slug.lower(),
        name=name,
        description=description,
        created_by_user_id=creator_user.id,
    )
    db.add(c)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise CommunitySlugTaken(slug) from None

    db.add(CommunityMember(community_id=c.id, user_id=creator_user.id, role="owner"))
    db.flush()

    emit_event(
        db,
        event_type="community.community.created",
        user_id=creator_user.id,
        entity_type="community",
        entity_id=c.id,
        payload={"slug": c.slug, "name": c.name},
    )
    _audit(db, action="community.community.created", user_id=creator_user.id, community_id=c.id,
           payload={"slug": c.slug})
    return c


def update_community(
    db: Session, *, owner_user: User, community: Community,
    name: str | None = None, description: str | None = None,
) -> Community:
    _require_owner(db, user=owner_user, community=community)
    changed: dict[str, object] = {}
    if name is not None:
        community.name = name
        changed["name"] = name
    if description is not None:
        community.description = description
        changed["description"] = description
    if changed:
        db.flush()
        _audit(db, action="community.community.updated", user_id=owner_user.id,
               community_id=community.id, payload={"changed": changed})
    return community


def soft_delete_community(db: Session, *, owner_user: User, community: Community) -> None:
    _require_owner(db, user=owner_user, community=community)
    community.deleted_at = datetime.now(UTC)
    db.flush()
    emit_event(
        db,
        event_type="community.community.deleted",
        user_id=owner_user.id,
        entity_type="community",
        entity_id=community.id,
        payload={"slug": community.slug},
    )
    _audit(db, action="community.community.deleted", user_id=owner_user.id, community_id=community.id)


def leave_community(db: Session, *, user: User, community: Community) -> None:
    member = (
        db.query(CommunityMember)
        .filter_by(community_id=community.id, user_id=user.id)
        .one_or_none()
    )
    if member is None:
        raise NotACommunityMember(f"user {user.id} is not a member of community {community.id}")
    if member.role == "owner":
        # If they are the *only* owner, refuse — owner must soft-delete the community.
        other_owners = (
            db.query(CommunityMember)
            .filter(
                CommunityMember.community_id == community.id,
                CommunityMember.role == "owner",
                CommunityMember.user_id != user.id,
            )
            .count()
        )
        if other_owners == 0:
            raise SoleOwnerCannotLeave(str(community.id))
    db.delete(member)
    db.flush()
    emit_event(
        db,
        event_type="community.member.left",
        user_id=user.id,
        entity_type="community",
        entity_id=community.id,
    )


def list_my_communities(db: Session, *, user: User) -> list[tuple[Community, CommunityMember]]:
    """Communities the user currently belongs to (with role)."""
    rows = (
        db.query(Community, CommunityMember)
        .join(CommunityMember, CommunityMember.community_id == Community.id)
        .filter(
            CommunityMember.user_id == user.id,
            Community.deleted_at.is_(None),
        )
        .order_by(Community.name)
        .all()
    )
    return rows
```

- [ ] **Step 4: Run the tests + full suite**

Run: `uv run pytest tests/test_community_communities_service.py -v && uv run pytest -q`
Expected: 7 passed; full suite zero regressions.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/services/community/communities.py apps/backend/tests/test_community_communities_service.py
git commit -m "feat(community): communities service (create, get, update, soft-delete, leave)"
```

---

### Task 4: `join_requests` service (with approval idempotency)

**Files:**
- Create: `apps/backend/app/services/community/join_requests.py`
- Test: `apps/backend/tests/test_community_join_requests_service.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_community_join_requests_service.py`:

```python
"""Tests for the join-requests service. Idempotency on approve is the key safety property."""
from __future__ import annotations

import uuid

import pytest

from app.auth import DEV_USER_ID
from app.models.community import (
    CommunityJoinRequest, CommunityMember,
)
from app.models.core import AuditLog, Event, User
from app.services.community import communities as community_svc
from app.services.community import join_requests as svc
from app.services.community.join_requests import (
    AlreadyAMember,
    AlreadyDecided,
    AlreadyPending,
    JoinRequestNotFound,
)


def _make_community_and_second_user(db):
    """Create a community owned by DEV_USER and a second user who'll request to join."""
    owner = db.get(User, DEV_USER_ID)
    c = community_svc.create_community(db, creator_user=owner, slug="js1", name="Join Suite 1")
    requester = User(
        id=uuid.uuid4(),
        email=f"req-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Requester",
    )
    db.add(requester)
    db.flush()
    return c, owner, requester


def test_request_to_join_creates_pending(db):
    c, _, requester = _make_community_and_second_user(db)
    req = svc.request_to_join(db, user=requester, community=c)
    assert req.status == "pending"
    assert db.query(Event).filter_by(event_type="community.join_request.requested").count() == 1


def test_request_to_join_rejects_duplicate_pending(db):
    c, _, requester = _make_community_and_second_user(db)
    svc.request_to_join(db, user=requester, community=c)
    with pytest.raises(AlreadyPending):
        svc.request_to_join(db, user=requester, community=c)


def test_request_to_join_rejects_existing_member(db):
    c, owner, _ = _make_community_and_second_user(db)
    # Owner is already a member.
    with pytest.raises(AlreadyAMember):
        svc.request_to_join(db, user=owner, community=c)


def test_approve_request_creates_membership_and_is_idempotent(db):
    c, owner, requester = _make_community_and_second_user(db)
    req = svc.request_to_join(db, user=requester, community=c)
    member = svc.approve_request(db, owner_user=owner, request=req)
    assert member.role == "member"
    db.refresh(req)
    assert req.status == "approved"
    # Second approve raises (request is no longer pending).
    with pytest.raises(AlreadyDecided):
        svc.approve_request(db, owner_user=owner, request=req)
    # Audit row was written.
    assert db.query(AuditLog).filter_by(action="community.join_request.approved").count() == 1


def test_decline_request(db):
    c, owner, requester = _make_community_and_second_user(db)
    req = svc.request_to_join(db, user=requester, community=c)
    svc.decline_request(db, owner_user=owner, request=req, note="not yet")
    db.refresh(req)
    assert req.status == "declined"
    assert req.decision_note == "not yet"
    # The user has no membership.
    assert (
        db.query(CommunityMember)
        .filter_by(community_id=c.id, user_id=requester.id)
        .count() == 0
    )


def test_decline_already_decided_request_is_rejected(db):
    c, owner, requester = _make_community_and_second_user(db)
    req = svc.request_to_join(db, user=requester, community=c)
    svc.decline_request(db, owner_user=owner, request=req)
    with pytest.raises(AlreadyDecided):
        svc.decline_request(db, owner_user=owner, request=req)


def test_withdraw_request(db):
    c, _, requester = _make_community_and_second_user(db)
    req = svc.request_to_join(db, user=requester, community=c)
    svc.withdraw_request(db, user=requester, request=req)
    db.refresh(req)
    assert req.status == "withdrawn"


def test_list_pending_excludes_decided(db):
    c, owner, requester = _make_community_and_second_user(db)
    svc.request_to_join(db, user=requester, community=c)
    other_user = User(id=uuid.uuid4(), email=f"o-{uuid.uuid4().hex[:6]}@x.com", display_name="o")
    db.add(other_user); db.flush()
    req2 = svc.request_to_join(db, user=other_user, community=c)
    svc.decline_request(db, owner_user=owner, request=req2)
    pending = svc.list_pending_requests(db, community=c)
    assert len(pending) == 1


def test_get_request_or_404(db):
    with pytest.raises(JoinRequestNotFound):
        svc.get_request_or_404(db, uuid.uuid4())
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_community_join_requests_service.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create the service**

Create `apps/backend/app/services/community/join_requests.py`:

```python
"""Community join-request service. The approval path is idempotent via a
conditional UPDATE: only a pending row transitions; concurrent approves race
safely (one wins, the rest see AlreadyDecided)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.community import (
    Community,
    CommunityJoinRequest,
    CommunityMember,
)
from app.models.core import AuditLog, User
from app.services.community.communities import _require_owner
from app.services.events import emit_event


class JoinRequestNotFound(Exception):
    pass


class AlreadyPending(Exception):
    pass


class AlreadyAMember(Exception):
    pass


class AlreadyDecided(Exception):
    """Request is no longer pending — already approved/declined/withdrawn."""


def _audit(db: Session, *, action: str, user_id, community_id, payload: dict | None = None) -> None:
    db.add(AuditLog(
        actor_user_id=user_id,
        action=action,
        target_type="community",
        target_id=community_id,
        payload=payload or {},
    ))


def get_request_or_404(db: Session, request_id: uuid.UUID) -> CommunityJoinRequest:
    req = db.get(CommunityJoinRequest, request_id)
    if req is None:
        raise JoinRequestNotFound(str(request_id))
    return req


def request_to_join(
    db: Session, *, user: User, community: Community,
) -> CommunityJoinRequest:
    """Open a pending request. 409 if already a member or a pending request exists."""
    existing_member = (
        db.query(CommunityMember)
        .filter_by(community_id=community.id, user_id=user.id)
        .one_or_none()
    )
    if existing_member is not None:
        raise AlreadyAMember(f"user {user.id} is already a member of community {community.id}")

    req = CommunityJoinRequest(
        community_id=community.id, user_id=user.id, status="pending",
    )
    db.add(req)
    try:
        db.flush()
    except IntegrityError:
        # Partial unique index `ux_pending_per_user_per_community` was violated.
        db.rollback()
        raise AlreadyPending(str(community.id)) from None

    emit_event(
        db,
        event_type="community.join_request.requested",
        user_id=user.id,
        entity_type="community",
        entity_id=community.id,
    )
    return req


def withdraw_request(
    db: Session, *, user: User, request: CommunityJoinRequest,
) -> CommunityJoinRequest:
    """The requester withdraws their own pending request."""
    if request.user_id != user.id:
        raise JoinRequestNotFound(str(request.id))  # don't reveal someone else's request
    if request.status != "pending":
        raise AlreadyDecided(request.status)
    request.status = "withdrawn"
    request.decided_at = datetime.now(UTC)
    db.flush()
    return request


def approve_request(
    db: Session, *, owner_user: User, request: CommunityJoinRequest,
) -> CommunityMember:
    """Approve a pending request → create membership. Atomic + idempotent: a
    conditional UPDATE on `status='pending'` ensures concurrent approves are safe."""
    community = db.get(Community, request.community_id)
    if community is None or community.deleted_at is not None:
        raise JoinRequestNotFound(str(request.id))
    _require_owner(db, user=owner_user, community=community)

    now = datetime.now(UTC)
    result = db.execute(
        update(CommunityJoinRequest)
        .where(
            CommunityJoinRequest.id == request.id,
            CommunityJoinRequest.status == "pending",
        )
        .values(
            status="approved",
            decided_at=now,
            decided_by_user_id=owner_user.id,
        )
    )
    if result.rowcount == 0:
        raise AlreadyDecided("approved-or-already-decided")

    # Create membership (idempotent against the unique constraint — if a race
    # somehow created it elsewhere, swallow and return the existing).
    existing = (
        db.query(CommunityMember)
        .filter_by(community_id=community.id, user_id=request.user_id)
        .one_or_none()
    )
    if existing is None:
        existing = CommunityMember(
            community_id=community.id, user_id=request.user_id, role="member",
        )
        db.add(existing)
        db.flush()

    emit_event(
        db,
        event_type="community.member.joined",
        user_id=request.user_id,
        entity_type="community",
        entity_id=community.id,
        payload={"approved_by_user_id": str(owner_user.id)},
    )
    emit_event(
        db,
        event_type="community.join_request.approved",
        user_id=owner_user.id,
        entity_type="community",
        entity_id=community.id,
        payload={"request_id": str(request.id), "joiner_user_id": str(request.user_id)},
    )
    _audit(db, action="community.join_request.approved", user_id=owner_user.id,
           community_id=community.id,
           payload={"request_id": str(request.id), "joiner_user_id": str(request.user_id)})
    return existing


def decline_request(
    db: Session, *, owner_user: User, request: CommunityJoinRequest, note: str | None = None,
) -> CommunityJoinRequest:
    community = db.get(Community, request.community_id)
    if community is None or community.deleted_at is not None:
        raise JoinRequestNotFound(str(request.id))
    _require_owner(db, user=owner_user, community=community)

    now = datetime.now(UTC)
    result = db.execute(
        update(CommunityJoinRequest)
        .where(
            CommunityJoinRequest.id == request.id,
            CommunityJoinRequest.status == "pending",
        )
        .values(
            status="declined",
            decided_at=now,
            decided_by_user_id=owner_user.id,
            decision_note=note,
        )
    )
    if result.rowcount == 0:
        raise AlreadyDecided("declined-or-already-decided")

    db.refresh(request)
    emit_event(
        db,
        event_type="community.join_request.declined",
        user_id=owner_user.id,
        entity_type="community",
        entity_id=community.id,
        payload={"request_id": str(request.id)},
    )
    _audit(db, action="community.join_request.declined", user_id=owner_user.id,
           community_id=community.id,
           payload={"request_id": str(request.id), "note": note})
    return request


def list_pending_requests(
    db: Session, *, community: Community,
) -> list[CommunityJoinRequest]:
    return (
        db.query(CommunityJoinRequest)
        .filter(
            CommunityJoinRequest.community_id == community.id,
            CommunityJoinRequest.status == "pending",
        )
        .order_by(CommunityJoinRequest.requested_at)
        .all()
    )
```

- [ ] **Step 4: Run the tests + full suite**

Run: `uv run pytest tests/test_community_join_requests_service.py -v && uv run pytest -q`
Expected: 9 passed; full suite zero regressions.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/services/community/join_requests.py apps/backend/tests/test_community_join_requests_service.py
git commit -m "feat(community): join-requests service with idempotent approve"
```

---

### Task 5: `listings` service + `items.py` cascade hooks

**Files:**
- Create: `apps/backend/app/services/community/listings.py`
- Modify: `apps/backend/app/services/community/items.py`
- Test: `apps/backend/tests/test_community_listings_service.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_community_listings_service.py`:

```python
"""Tests for the listings service + the items.py cascade hooks."""
from __future__ import annotations

import uuid

import pytest

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.community import (
    CommunityItem, CommunityMember, Listing, ListingCommunity,
)
from app.models.core import AuditLog, Event, Household, User
from app.services.community import communities as community_svc
from app.services.community import items as items_svc
from app.services.community import listings as svc
from app.services.community.listings import (
    CommunityNotPermittedForListing,
    ListingNotFound,
    OneActiveListingPerItem,
    QuantityExceedsItem,
)


def _ctx(db):
    return db.get(Household, DEV_HOUSEHOLD_ID), db.get(User, DEV_USER_ID)


def test_create_listing_minimal(db):
    h, u = _ctx(db)
    item = items_svc.create_item(db, household=h, user=u, name="Drill", quantity=1)
    listing = svc.create_listing(
        db, household=h, user=u, item_id=item.id,
        allowed_exchange_types=["borrow"], quantity_available=1,
        community_ids=[], share_in_radius=False,
    )
    assert listing.availability_status == "available"
    assert listing.share_in_radius is False
    assert db.query(Event).filter_by(event_type="community.listing.created").count() == 1


def test_create_listing_rejects_quantity_exceeding_item(db):
    h, u = _ctx(db)
    item = items_svc.create_item(db, household=h, user=u, name="Chairs", quantity=4)
    with pytest.raises(QuantityExceedsItem):
        svc.create_listing(
            db, household=h, user=u, item_id=item.id,
            allowed_exchange_types=["borrow"], quantity_available=5,
            community_ids=[], share_in_radius=False,
        )


def test_create_listing_rejects_community_user_not_in(db):
    h, u = _ctx(db)
    other_user = User(id=uuid.uuid4(), email=f"x-{uuid.uuid4().hex[:6]}@x.com", display_name="x")
    db.add(other_user); db.flush()
    item = items_svc.create_item(db, household=h, user=u, name="Tent", quantity=1)
    c = community_svc.create_community(db, creator_user=other_user, slug="foreign", name="Foreign")
    with pytest.raises(CommunityNotPermittedForListing):
        svc.create_listing(
            db, household=h, user=u, item_id=item.id,
            allowed_exchange_types=["borrow"], quantity_available=1,
            community_ids=[c.id], share_in_radius=False,
        )


def test_create_listing_with_user_community(db):
    h, u = _ctx(db)
    c = community_svc.create_community(db, creator_user=u, slug="mine", name="Mine")
    item = items_svc.create_item(db, household=h, user=u, name="Tent", quantity=1)
    listing = svc.create_listing(
        db, household=h, user=u, item_id=item.id,
        allowed_exchange_types=["borrow"], quantity_available=1,
        community_ids=[c.id], share_in_radius=False,
    )
    assert (
        db.query(ListingCommunity)
        .filter_by(listing_id=listing.id, community_id=c.id)
        .count() == 1
    )


def test_create_listing_one_active_per_item(db):
    h, u = _ctx(db)
    item = items_svc.create_item(db, household=h, user=u, name="Catan", quantity=1)
    svc.create_listing(
        db, household=h, user=u, item_id=item.id,
        allowed_exchange_types=["borrow"], quantity_available=1,
        community_ids=[], share_in_radius=False,
    )
    with pytest.raises(OneActiveListingPerItem):
        svc.create_listing(
            db, household=h, user=u, item_id=item.id,
            allowed_exchange_types=["gift"], quantity_available=1,
            community_ids=[], share_in_radius=False,
        )


def test_soft_delete_item_cascades_to_listing(db):
    """Audit fix #1 — soft-deleting an item soft-deletes its active listing."""
    h, u = _ctx(db)
    item = items_svc.create_item(db, household=h, user=u, name="Saw", quantity=1)
    listing = svc.create_listing(
        db, household=h, user=u, item_id=item.id,
        allowed_exchange_types=["borrow"], quantity_available=1,
        community_ids=[], share_in_radius=False,
    )
    items_svc.soft_delete_item(db, household=h, user=u, item_id=item.id)
    db.refresh(listing)
    assert listing.deleted_at is not None
    assert listing.availability_status == "removed"
    assert db.query(Event).filter_by(event_type="community.listing.removed").count() == 1


def test_update_item_quantity_reconciles_listing(db):
    """Audit fix #7 — reducing item.quantity caps the listing's quantity_available."""
    h, u = _ctx(db)
    item = items_svc.create_item(db, household=h, user=u, name="Chairs", quantity=8)
    listing = svc.create_listing(
        db, household=h, user=u, item_id=item.id,
        allowed_exchange_types=["borrow"], quantity_available=6,
        community_ids=[], share_in_radius=False,
    )
    items_svc.update_item(db, household=h, user=u, item_id=item.id, quantity=3)
    db.refresh(listing)
    assert listing.quantity_available == 3


def test_update_item_quantity_to_zero_removes_listing(db):
    h, u = _ctx(db)
    item = items_svc.create_item(db, household=h, user=u, name="X", quantity=2)
    listing = svc.create_listing(
        db, household=h, user=u, item_id=item.id,
        allowed_exchange_types=["gift"], quantity_available=2,
        community_ids=[], share_in_radius=False,
    )
    items_svc.update_item(db, household=h, user=u, item_id=item.id, quantity=0)
    db.refresh(listing)
    assert listing.deleted_at is not None
    assert listing.availability_status == "removed"


def test_update_listing_editor_can_only_add_communities_they_belong_to(db):
    """Audit fix #3 — Bob can't add a community Bob isn't in, even if Alice (the
    original creator) was in it."""
    h, u = _ctx(db)  # u is Alice (DEV_USER)
    alice_community = community_svc.create_community(db, creator_user=u, slug="ac", name="Alice's")
    item = items_svc.create_item(db, household=h, user=u, name="Item", quantity=1)
    listing = svc.create_listing(
        db, household=h, user=u, item_id=item.id,
        allowed_exchange_types=["borrow"], quantity_available=1,
        community_ids=[alice_community.id], share_in_radius=False,
    )
    # Now Bob — another user — is a member of the same household but NOT of any community.
    bob = User(id=uuid.uuid4(), email=f"b-{uuid.uuid4().hex[:6]}@x.com", display_name="Bob")
    db.add(bob); db.flush()
    from app.models.core import HouseholdMember
    db.add(HouseholdMember(user_id=bob.id, household_id=h.id, role="member"))
    db.flush()
    # A community Bob isn't in (someone else owns it)
    other = User(id=uuid.uuid4(), email=f"o-{uuid.uuid4().hex[:6]}@x.com", display_name="O")
    db.add(other); db.flush()
    other_community = community_svc.create_community(
        db, creator_user=other, slug="oc", name="Other's"
    )
    # Bob tries to add other_community to the listing — must be rejected.
    with pytest.raises(CommunityNotPermittedForListing):
        svc.update_listing(
            db, household=h, user=bob, listing_id=listing.id,
            community_ids=[alice_community.id, other_community.id],
        )
    # But Bob CAN remove alice_community (existing pick), even though he isn't in it.
    svc.update_listing(
        db, household=h, user=bob, listing_id=listing.id, community_ids=[],
    )
    assert (
        db.query(ListingCommunity).filter_by(listing_id=listing.id).count() == 0
    )


def test_soft_delete_listing(db):
    h, u = _ctx(db)
    item = items_svc.create_item(db, household=h, user=u, name="X", quantity=1)
    listing = svc.create_listing(
        db, household=h, user=u, item_id=item.id,
        allowed_exchange_types=["gift"], quantity_available=1,
        community_ids=[], share_in_radius=False,
    )
    svc.soft_delete_listing(db, household=h, user=u, listing_id=listing.id)
    db.refresh(listing)
    assert listing.deleted_at is not None
    assert listing.availability_status == "removed"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_community_listings_service.py -v`
Expected: FAIL with `ModuleNotFoundError` for `app.services.community.listings`.

- [ ] **Step 3: Create the listings service**

Create `apps/backend/app/services/community/listings.py`:

```python
"""Listings service — create / update (with editor-scope) / soft-delete + the
`reconcile_listings_for_item` hook that the items service calls when an item
is soft-deleted or its quantity changes."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.community import (
    CommunityItem,
    CommunityMember,
    Listing,
    ListingCommunity,
)
from app.models.core import AuditLog, Household, HouseholdMember, User
from app.services.events import emit_event


class ListingNotFound(Exception):
    pass


class OneActiveListingPerItem(Exception):
    """Partial unique index `ux_one_active_listing_per_item` was violated."""


class QuantityExceedsItem(Exception):
    pass


class CommunityNotPermittedForListing(Exception):
    """User tried to add a listing to a community they aren't a member of."""


class NotHouseholdMember(Exception):
    pass


def _require_household_member(db: Session, *, user: User, household: Household) -> HouseholdMember:
    """Caller must be `owner` or `member` (not `viewer`) of the household."""
    m = (
        db.query(HouseholdMember)
        .filter_by(user_id=user.id, household_id=household.id)
        .one_or_none()
    )
    if m is None or m.role not in ("owner", "member"):
        raise NotHouseholdMember(f"user {user.id} cannot act on household {household.id}")
    return m


def _user_community_ids(db: Session, user: User) -> set[uuid.UUID]:
    rows = db.query(CommunityMember.community_id).filter(
        CommunityMember.user_id == user.id
    ).all()
    return {r[0] for r in rows}


def _load_item_owned_by(db: Session, *, household: Household, item_id: uuid.UUID) -> CommunityItem:
    item = db.get(CommunityItem, item_id)
    if item is None or item.deleted_at is not None or item.household_id != household.id:
        raise ListingNotFound(f"item {item_id} not found for household {household.id}")
    return item


def get_listing_for_household(
    db: Session, *, household: Household, listing_id: uuid.UUID,
) -> Listing:
    """Load a listing owned (via the item) by the given household. Raises ListingNotFound."""
    listing = db.get(Listing, listing_id)
    if listing is None or listing.deleted_at is not None:
        raise ListingNotFound(str(listing_id))
    item = db.get(CommunityItem, listing.item_id)
    if item is None or item.household_id != household.id:
        raise ListingNotFound(str(listing_id))
    return listing


def _audit(db: Session, *, action: str, user_id, listing_id, payload: dict | None = None) -> None:
    db.add(AuditLog(
        actor_user_id=user_id,
        action=action,
        target_type="listing",
        target_id=listing_id,
        payload=payload or {},
    ))


def create_listing(
    db: Session,
    *,
    household: Household,
    user: User,
    item_id: uuid.UUID,
    allowed_exchange_types: list[str],
    quantity_available: int,
    community_ids: list[uuid.UUID],
    share_in_radius: bool,
    share_radius_miles: int | None = None,
    description_override: str | None = None,
) -> Listing:
    _require_household_member(db, user=user, household=household)
    item = _load_item_owned_by(db, household=household, item_id=item_id)
    if quantity_available > item.quantity:
        raise QuantityExceedsItem(
            f"listing quantity {quantity_available} > item quantity {item.quantity}"
        )
    user_communities = _user_community_ids(db, user)
    bad = [cid for cid in community_ids if cid not in user_communities]
    if bad:
        raise CommunityNotPermittedForListing(
            f"user {user.id} is not a member of communities {bad}"
        )

    listing = Listing(
        item_id=item.id,
        created_by_user_id=user.id,
        allowed_exchange_types=allowed_exchange_types,
        quantity_available=quantity_available,
        share_in_radius=share_in_radius,
        share_radius_miles=share_radius_miles,
        availability_status="available",
        description_override=description_override,
    )
    db.add(listing)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise OneActiveListingPerItem(str(item_id)) from None

    for cid in community_ids:
        db.add(ListingCommunity(
            listing_id=listing.id, community_id=cid, added_by_user_id=user.id,
        ))
    db.flush()

    emit_event(
        db,
        event_type="community.listing.created",
        household_id=household.id,
        user_id=user.id,
        entity_type="listing",
        entity_id=listing.id,
        payload={
            "item_id": str(item.id),
            "allowed_exchange_types": allowed_exchange_types,
            "share_in_radius": share_in_radius,
            "community_count": len(community_ids),
        },
    )
    _audit(db, action="community.listing.created", user_id=user.id, listing_id=listing.id,
           payload={"item_id": str(item.id)})
    return listing


def update_listing(
    db: Session,
    *,
    household: Household,
    user: User,
    listing_id: uuid.UUID,
    allowed_exchange_types: list[str] | None = None,
    quantity_available: int | None = None,
    community_ids: list[uuid.UUID] | None = None,
    share_in_radius: bool | None = None,
    share_radius_miles: int | None = None,
    description_override: str | None = None,
    availability_status: str | None = None,
) -> Listing:
    _require_household_member(db, user=user, household=household)
    listing = get_listing_for_household(db, household=household, listing_id=listing_id)
    item = db.get(CommunityItem, listing.item_id)
    assert item is not None  # checked by get_listing_for_household

    changed: dict[str, object] = {}
    if allowed_exchange_types is not None:
        listing.allowed_exchange_types = allowed_exchange_types
        changed["allowed_exchange_types"] = allowed_exchange_types
    if quantity_available is not None:
        if quantity_available > item.quantity:
            raise QuantityExceedsItem(
                f"listing quantity {quantity_available} > item quantity {item.quantity}"
            )
        listing.quantity_available = quantity_available
        changed["quantity_available"] = quantity_available
    if share_in_radius is not None:
        listing.share_in_radius = share_in_radius
        changed["share_in_radius"] = share_in_radius
    if share_radius_miles is not None:
        listing.share_radius_miles = share_radius_miles
        changed["share_radius_miles"] = share_radius_miles
    if description_override is not None:
        listing.description_override = description_override
        changed["description_override"] = description_override
    if availability_status is not None:
        listing.availability_status = availability_status
        changed["availability_status"] = availability_status

    if community_ids is not None:
        # Editor-scope check: any community being *added* must be in the editor's
        # current memberships. Removals are always allowed.
        current = {
            r.community_id for r in
            db.query(ListingCommunity).filter_by(listing_id=listing.id).all()
        }
        desired = set(community_ids)
        added = desired - current
        if added:
            user_communities = _user_community_ids(db, user)
            forbidden = [cid for cid in added if cid not in user_communities]
            if forbidden:
                raise CommunityNotPermittedForListing(
                    f"user {user.id} is not a member of communities {forbidden}"
                )
        # Apply removals, then additions.
        for cid in current - desired:
            db.query(ListingCommunity).filter_by(
                listing_id=listing.id, community_id=cid
            ).delete()
        for cid in added:
            db.add(ListingCommunity(
                listing_id=listing.id, community_id=cid, added_by_user_id=user.id,
            ))
        changed["community_ids"] = sorted(str(c) for c in desired)

    if changed:
        db.flush()
        emit_event(
            db,
            event_type="community.listing.updated",
            household_id=household.id,
            user_id=user.id,
            entity_type="listing",
            entity_id=listing.id,
            payload={"changed": list(changed.keys())},
        )
    return listing


def soft_delete_listing(
    db: Session, *, household: Household, user: User, listing_id: uuid.UUID,
    reason: str = "user_request",
) -> Listing:
    _require_household_member(db, user=user, household=household)
    listing = get_listing_for_household(db, household=household, listing_id=listing_id)
    listing.deleted_at = datetime.now(UTC)
    listing.availability_status = "removed"
    db.flush()
    emit_event(
        db,
        event_type="community.listing.removed",
        household_id=household.id,
        user_id=user.id,
        entity_type="listing",
        entity_id=listing.id,
        payload={"reason": reason},
    )
    return listing


def reconcile_listings_for_item(
    db: Session, *, item: CommunityItem, actor_user_id: uuid.UUID,
) -> None:
    """Called by the items service when an item is soft-deleted or its quantity changes.

    Behaviors:
    - Item soft-deleted (item.deleted_at is not None) → soft-delete the active listing.
    - Item quantity dropped to 0 → soft-delete the active listing.
    - Item quantity reduced but >0 → cap listing.quantity_available.
    No-op when no active listing exists.
    """
    listing = (
        db.query(Listing)
        .filter(
            Listing.item_id == item.id,
            Listing.deleted_at.is_(None),
            Listing.availability_status != "removed",
        )
        .one_or_none()
    )
    if listing is None:
        return

    now = datetime.now(UTC)
    if item.deleted_at is not None or item.quantity <= 0:
        listing.deleted_at = now
        listing.availability_status = "removed"
        db.flush()
        emit_event(
            db,
            event_type="community.listing.removed",
            household_id=item.household_id,
            user_id=actor_user_id,
            entity_type="listing",
            entity_id=listing.id,
            payload={"reason": "item_cascade"},
        )
        return

    # Cap quantity if item quantity dropped below the listing's offer.
    if listing.quantity_available > item.quantity:
        listing.quantity_available = item.quantity
        db.flush()
        emit_event(
            db,
            event_type="community.listing.updated",
            household_id=item.household_id,
            user_id=actor_user_id,
            entity_type="listing",
            entity_id=listing.id,
            payload={"changed": ["quantity_available"], "reason": "item_cascade"},
        )
```

- [ ] **Step 4: Extend `app/services/community/items.py` to call the reconciler**

In `apps/backend/app/services/community/items.py`, modify two functions. **At the top, add this import** (after the existing imports):

```python
# Avoid a top-level circular import: listings.py imports from this file too.
def _reconcile_listings(db: Session, *, item: CommunityItem, actor_user_id) -> None:
    from app.services.community.listings import reconcile_listings_for_item
    reconcile_listings_for_item(db, item=item, actor_user_id=actor_user_id)
```

(Place that helper just above `class CommunityItemNotFound(Exception):`.)

Then in `soft_delete_item`, after `db.flush()` and before `emit_event(...)`, add:

```python
    _reconcile_listings(db, item=item, actor_user_id=user.id)
```

And in `update_item`, after the existing `db.flush()` (when `changed` is non-empty) and before `emit_event(...)`, add:

```python
    if "quantity" in changed:
        _reconcile_listings(db, item=item, actor_user_id=user.id)
```

- [ ] **Step 5: Run the tests + full suite**

Run: `uv run pytest tests/test_community_listings_service.py -v && uv run pytest -q`
Expected: 10 passed; full suite zero regressions.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/services/community/listings.py \
  apps/backend/app/services/community/items.py \
  apps/backend/tests/test_community_listings_service.py
git commit -m "feat(community): listings service + item soft-delete/quantity cascade to listings"
```

---

### Task 6: The visibility helper + cross-household isolation tests

**Files:**
- Create: `apps/backend/app/services/community/visibility.py`
- Modify: `apps/backend/tests/conftest.py` (add second_household fixture + location helper)
- Test: `apps/backend/tests/test_community_visibility.py`

This is the security gate. It MUST be built and tested before the feed endpoint (Task 10).

- [ ] **Step 1: Add the `second_household` fixture and location helper to conftest**

In `apps/backend/tests/conftest.py`, add these constants near the top (after the existing `DEV_*` imports):

```python
import uuid as _uuid_for_fixture

SECOND_USER_ID = _uuid_for_fixture.UUID("00000000-0000-0000-0000-000000000011")
SECOND_HOUSEHOLD_ID = _uuid_for_fixture.UUID("00000000-0000-0000-0000-000000000012")
SECOND_USER_EMAIL = "second@frugal-living.local"
```

Inside `_seed_test_user_and_household()`, immediately before `db_.commit()`, append a parallel block:

```python
        second_user = db_.get(User, SECOND_USER_ID)
        if second_user is None:
            db_.add(User(id=SECOND_USER_ID, email=SECOND_USER_EMAIL, display_name="Second User"))
            db_.flush()

        second_household = db_.get(Household, SECOND_HOUSEHOLD_ID)
        if second_household is None:
            db_.add(Household(id=SECOND_HOUSEHOLD_ID, name="Second Household", size=1))
            db_.flush()

        if (
            db_.query(HouseholdMember)
            .filter_by(user_id=SECOND_USER_ID, household_id=SECOND_HOUSEHOLD_ID)
            .one_or_none() is None
        ):
            db_.add(HouseholdMember(
                user_id=SECOND_USER_ID, household_id=SECOND_HOUSEHOLD_ID, role="owner",
            ))

        if db_.query(Subscription).filter_by(user_id=SECOND_USER_ID).one_or_none() is None:
            db_.add(Subscription(
                user_id=SECOND_USER_ID, plan="free", status="active",
                tier_a_enabled=True, tier_b_enabled=True,
            ))
```

Append two new fixtures at the very end of the file:

```python
@pytest.fixture
def second_household(db) -> Household:
    """The second seeded household (separate from the default DEV_HOUSEHOLD_ID).
    For tests that need two households to exercise cross-household visibility."""
    h = db.get(Household, SECOND_HOUSEHOLD_ID)
    assert h is not None
    return h


@pytest.fixture
def second_user(db) -> User:
    u = db.get(User, SECOND_USER_ID)
    assert u is not None
    return u


def set_household_location(db, household: Household, lat: float, lng: float) -> None:
    """Test helper — write lat/lng into the household's metadata_ JSONB."""
    md = dict(household.metadata_ or {})
    md["lat"] = lat
    md["lng"] = lng
    household.metadata_ = md
    db.flush()
```

Also update the per-test cleanup in `_clean_household_data` to wipe `SECOND_HOUSEHOLD_ID`'s rows alongside `DEV_HOUSEHOLD_ID`. Inside the function, after every `db_.query(X).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()` line, add a parallel line for `SECOND_HOUSEHOLD_ID`. Then in the existing community deletes from Task 1, those use `.delete()` without a filter so they already cover both.

Specifically, for these existing lines:

```python
        db_.query(FoodWasteEvent).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        db_.query(PreservationJob).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        db_.query(ShoppingList).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        db_.query(MealPlan).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        db_.query(PantryItem).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        db_.query(CommunityItem).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        ...
        db_.query(Briefing).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        ...
        db_.query(Conversation).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
```

After each, add the parallel `SECOND_HOUSEHOLD_ID` line. Reset household location too — at the top of the function, add:

```python
        for hid in (DEV_HOUSEHOLD_ID, SECOND_HOUSEHOLD_ID):
            h = db_.get(Household, hid)
            if h is not None:
                md = dict(h.metadata_ or {})
                md.pop("lat", None)
                md.pop("lng", None)
                md.pop("share_radius_miles", None)
                h.metadata_ = md
```

- [ ] **Step 2: Write the failing test**

Create `apps/backend/tests/test_community_visibility.py`:

```python
"""Tests for the canonical visibility helper. This is the security gate.

Audit fixes #1, #2, #4 (cascade, read-time membership check, is_active/deleted filters)
all assert here.
"""
from __future__ import annotations

import pytest

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.community import CommunityMember, Listing
from app.models.core import Household, User
from app.services.community import communities as community_svc
from app.services.community import items as items_svc
from app.services.community import listings as listings_svc
from app.services.community import visibility


def _create_shared_listing(
    db, *, owner_household, owner_user, community=None, share_in_radius=False, share_radius_miles=None,
):
    item = items_svc.create_item(
        db, household=owner_household, user=owner_user, name="X", quantity=1,
    )
    listing = listings_svc.create_listing(
        db, household=owner_household, user=owner_user, item_id=item.id,
        allowed_exchange_types=["borrow"], quantity_available=1,
        community_ids=[community.id] if community else [],
        share_in_radius=share_in_radius,
        share_radius_miles=share_radius_miles,
    )
    return item, listing


# ---------- Community path ----------

def test_shared_community_visible_to_co_member(db, second_household, second_user):
    """Both households' users are members of community C; viewer sees lister's listing."""
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    c = community_svc.create_community(db, creator_user=owner, slug="cv1", name="cv1")
    # second_user joins by direct insertion (skipping the join-request flow for the unit test)
    db.add(CommunityMember(community_id=c.id, user_id=second_user.id, role="member"))
    db.flush()
    _, listing = _create_shared_listing(db, owner_household=owner_h, owner_user=owner, community=c)

    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id in [r.id for r in visible]


def test_listing_not_visible_after_lister_leaves_community(db, second_household, second_user):
    """Audit fix #2 — read-time membership check. Lister leaves community → no longer visible."""
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    c = community_svc.create_community(db, creator_user=owner, slug="cv2", name="cv2")
    db.add(CommunityMember(community_id=c.id, user_id=second_user.id, role="member"))
    db.flush()
    _, listing = _create_shared_listing(db, owner_household=owner_h, owner_user=owner, community=c)

    # Lister leaves (owner is sole owner, so we delete via membership delete directly for the test).
    owner_membership = (
        db.query(CommunityMember).filter_by(community_id=c.id, user_id=owner.id).one()
    )
    db.delete(owner_membership)
    db.flush()

    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id not in [r.id for r in visible]


def test_listing_not_visible_in_soft_deleted_community(db, second_household, second_user):
    """Audit fix #4 — community.deleted_at IS NULL filter."""
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    c = community_svc.create_community(db, creator_user=owner, slug="cv3", name="cv3")
    db.add(CommunityMember(community_id=c.id, user_id=second_user.id, role="member"))
    db.flush()
    _, listing = _create_shared_listing(db, owner_household=owner_h, owner_user=owner, community=c)
    community_svc.soft_delete_community(db, owner_user=owner, community=c)

    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id not in [r.id for r in visible]


def test_listing_not_visible_when_lister_deactivated(db, second_household, second_user):
    """Audit fix #4 — users.is_active = true filter on the membership join."""
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    c = community_svc.create_community(db, creator_user=owner, slug="cv4", name="cv4")
    db.add(CommunityMember(community_id=c.id, user_id=second_user.id, role="member"))
    db.flush()
    _, listing = _create_shared_listing(db, owner_household=owner_h, owner_user=owner, community=c)

    owner.is_active = False
    db.flush()

    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id not in [r.id for r in visible]


def test_listing_not_visible_when_no_overlap(db, second_household, second_user):
    """Lister is in community A; viewer is in community B; no radius — not visible."""
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    a = community_svc.create_community(db, creator_user=owner, slug="cv5a", name="cv5a")
    b = community_svc.create_community(db, creator_user=second_user, slug="cv5b", name="cv5b")
    _, listing = _create_shared_listing(db, owner_household=owner_h, owner_user=owner, community=a)
    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id not in [r.id for r in visible]


def test_viewer_does_not_see_own_household_listings(db):
    """You don't browse your own listings on the feed."""
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    c = community_svc.create_community(db, creator_user=owner, slug="cv6", name="cv6")
    _, listing = _create_shared_listing(db, owner_household=owner_h, owner_user=owner, community=c)
    visible = visibility.listings_visible_to(
        db, viewer_household=owner_h, viewer_user=owner,
    ).all()
    assert listing.id not in [r.id for r in visible]


# ---------- Radius path ----------

def test_radius_visible_within_distance(db, second_household, second_user):
    from tests.conftest import set_household_location
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    # Two points ~0.1 mi apart in Brooklyn
    set_household_location(db, owner_h, 40.6782, -73.9442)
    set_household_location(db, second_household, 40.6796, -73.9442)

    _, listing = _create_shared_listing(
        db, owner_household=owner_h, owner_user=owner,
        share_in_radius=True, share_radius_miles=5,
    )
    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id in [r.id for r in visible]


def test_radius_not_visible_when_far(db, second_household, second_user):
    from tests.conftest import set_household_location
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    # Brooklyn and Boston ≈ 190 mi
    set_household_location(db, owner_h, 40.6782, -73.9442)
    set_household_location(db, second_household, 42.3601, -71.0589)

    _, listing = _create_shared_listing(
        db, owner_household=owner_h, owner_user=owner,
        share_in_radius=True, share_radius_miles=5,
    )
    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id not in [r.id for r in visible]


def test_radius_not_visible_when_lister_opted_out(db, second_household, second_user):
    """share_in_radius=False means even an adjacent household can't see via radius."""
    from tests.conftest import set_household_location
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    set_household_location(db, owner_h, 40.6782, -73.9442)
    set_household_location(db, second_household, 40.6796, -73.9442)

    _, listing = _create_shared_listing(
        db, owner_household=owner_h, owner_user=owner, share_in_radius=False,
    )
    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id not in [r.id for r in visible]


def test_radius_not_visible_when_viewer_has_no_location(db, second_household, second_user):
    from tests.conftest import set_household_location
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    set_household_location(db, owner_h, 40.6782, -73.9442)
    # second_household intentionally unset.

    _, listing = _create_shared_listing(
        db, owner_household=owner_h, owner_user=owner,
        share_in_radius=True, share_radius_miles=5,
    )
    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id not in [r.id for r in visible]


# ---------- Item / listing lifecycle ----------

def test_soft_deleted_listing_not_visible(db, second_household, second_user):
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    c = community_svc.create_community(db, creator_user=owner, slug="cv8", name="cv8")
    db.add(CommunityMember(community_id=c.id, user_id=second_user.id, role="member"))
    db.flush()
    _, listing = _create_shared_listing(db, owner_household=owner_h, owner_user=owner, community=c)
    listings_svc.soft_delete_listing(db, household=owner_h, user=owner, listing_id=listing.id)
    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id not in [r.id for r in visible]


def test_paused_listing_not_visible(db, second_household, second_user):
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    c = community_svc.create_community(db, creator_user=owner, slug="cv9", name="cv9")
    db.add(CommunityMember(community_id=c.id, user_id=second_user.id, role="member"))
    db.flush()
    _, listing = _create_shared_listing(db, owner_household=owner_h, owner_user=owner, community=c)
    listings_svc.update_listing(
        db, household=owner_h, user=owner, listing_id=listing.id,
        availability_status="paused",
    )
    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id not in [r.id for r in visible]


def test_listing_not_visible_after_item_soft_delete(db, second_household, second_user):
    """Audit fix #1 — item soft-delete cascades to listing, which then drops from feeds."""
    owner = db.get(User, DEV_USER_ID)
    owner_h = db.get(Household, DEV_HOUSEHOLD_ID)
    c = community_svc.create_community(db, creator_user=owner, slug="cv10", name="cv10")
    db.add(CommunityMember(community_id=c.id, user_id=second_user.id, role="member"))
    db.flush()
    item, listing = _create_shared_listing(
        db, owner_household=owner_h, owner_user=owner, community=c,
    )
    items_svc.soft_delete_item(db, household=owner_h, user=owner, item_id=item.id)
    visible = visibility.listings_visible_to(
        db, viewer_household=second_household, viewer_user=second_user,
    ).all()
    assert listing.id not in [r.id for r in visible]
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_community_visibility.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.community.visibility'`.

- [ ] **Step 4: Implement the visibility helper**

Create `apps/backend/app/services/community/visibility.py`:

```python
"""The canonical 'listings visible to (viewer)' query.

This is the single security gate for every cross-household read in Phase 2.
Every endpoint that surfaces another household's listing data MUST funnel
through `listings_visible_to(...)` — no exceptions.

Visibility = community-path OR radius-path, subject to liveness filters
(audit fixes #1, #2, #4):
  - listing.deleted_at IS NULL AND availability_status = 'available'
  - item.deleted_at IS NULL
  - owning household != viewer household
  - all traversed users are users.is_active = true
  - all traversed communities are communities.deleted_at IS NULL
  - community path: at least one *current* member of the owning household is
    also a current member of a community the listing is shared into
  - radius path: listing.share_in_radius = true AND distance(viewer.lat/lng,
    owner.lat/lng) <= effective_radius_miles (COALESCE listing → owner → 5)
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from sqlalchemy import Float, and_, exists, or_, select
from sqlalchemy.orm import Session, aliased

from app.models.community import (
    Community,
    CommunityItem,
    CommunityMember,
    Listing,
    ListingCommunity,
)
from app.models.core import Household, HouseholdMember, User

if TYPE_CHECKING:
    from sqlalchemy.orm import Query

DEFAULT_SHARE_RADIUS_MILES = 5

# Rough miles per degree latitude (constant); longitude varies with cos(lat).
_MILES_PER_DEGREE_LAT = 69.0


def _bounding_box(lat: float, lng: float, miles: float) -> tuple[float, float, float, float]:
    """(min_lat, max_lat, min_lng, max_lng) bracketing a circle of `miles` around (lat, lng)."""
    lat_delta = miles / _MILES_PER_DEGREE_LAT
    cos_lat = max(0.01, math.cos(math.radians(lat)))
    lng_delta = miles / (_MILES_PER_DEGREE_LAT * cos_lat)
    return (lat - lat_delta, lat + lat_delta, lng - lng_delta, lng + lng_delta)


def _haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in miles. Used for the final exact filter inside the bounding box."""
    R = 3958.8  # mean Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _household_lat_lng(household: Household) -> tuple[float, float] | None:
    md = household.metadata_ or {}
    lat = md.get("lat")
    lng = md.get("lng")
    if lat is None or lng is None:
        return None
    return float(lat), float(lng)


def _household_default_radius(household: Household) -> int:
    md = household.metadata_ or {}
    v = md.get("share_radius_miles")
    if v is None:
        return DEFAULT_SHARE_RADIUS_MILES
    return int(v)


def listings_visible_to(
    db: Session, *, viewer_household: Household, viewer_user: User,
) -> "Query[Listing]":
    """Return a Query of Listings visible to this (household, user). Callers may
    `.filter(...)` / `.order_by(...)` / `.limit(...)` on top — but the security
    gate is already inside this query and must not be bypassed."""

    OwnerHM = aliased(HouseholdMember)
    OwnerUser = aliased(User)
    SharedMember = aliased(CommunityMember)
    SharedMemberUser = aliased(User)

    # The community path: there exists a (listing_communities) row pointing at a
    # live community where at least one current member of the owning household
    # (whose user is active) is also a current member of that community.
    community_exists = (
        select(1)
        .select_from(ListingCommunity)
        .join(Community, Community.id == ListingCommunity.community_id)
        .join(OwnerHM, OwnerHM.household_id == CommunityItem.household_id)
        .join(OwnerUser, OwnerUser.id == OwnerHM.user_id)
        .join(
            SharedMember,
            and_(
                SharedMember.community_id == ListingCommunity.community_id,
                SharedMember.user_id == OwnerHM.user_id,
            ),
        )
        .join(SharedMemberUser, SharedMemberUser.id == SharedMember.user_id)
        .where(
            ListingCommunity.listing_id == Listing.id,
            Community.deleted_at.is_(None),
            OwnerUser.is_active.is_(True),
            SharedMemberUser.is_active.is_(True),
            # Also require: the viewer is a current member of that community.
            exists(
                select(1).where(
                    CommunityMember.community_id == ListingCommunity.community_id,
                    CommunityMember.user_id == viewer_user.id,
                )
            ),
        )
        .exists()
    )

    base = (
        db.query(Listing)
        .join(CommunityItem, CommunityItem.id == Listing.item_id)
        .filter(
            Listing.deleted_at.is_(None),
            Listing.availability_status == "available",
            CommunityItem.deleted_at.is_(None),
            CommunityItem.household_id != viewer_household.id,
        )
    )

    viewer_loc = _household_lat_lng(viewer_household)
    if viewer_loc is None:
        # No location → only community path is possible.
        return base.filter(community_exists)

    # Radius path: bounding box + exact distance check.
    # Use a generous outer box (max allowed user radius is 500 mi per schema) to
    # let Postgres narrow first; then a Python-side exact filter excludes corner cases.
    viewer_lat, viewer_lng = viewer_loc
    max_outer_radius = 500
    min_lat, max_lat, min_lng, max_lng = _bounding_box(viewer_lat, viewer_lng, max_outer_radius)
    # Cast JSONB values to float for comparison.
    OwnerHousehold = aliased(Household)
    lat_expr = OwnerHousehold.metadata_["lat"].astext.cast(Float)
    lng_expr = OwnerHousehold.metadata_["lng"].astext.cast(Float)

    box_subq = (
        db.query(Listing.id)
        .join(CommunityItem, CommunityItem.id == Listing.item_id)
        .join(OwnerHousehold, OwnerHousehold.id == CommunityItem.household_id)
        .filter(
            Listing.share_in_radius.is_(True),
            lat_expr.is_not(None),
            lng_expr.is_not(None),
            lat_expr.between(min_lat, max_lat),
            lng_expr.between(min_lng, max_lng),
            Listing.deleted_at.is_(None),
            Listing.availability_status == "available",
            CommunityItem.deleted_at.is_(None),
            CommunityItem.household_id != viewer_household.id,
        )
        .subquery()
    )

    box_q = db.query(Listing).filter(Listing.id.in_(select(box_subq.c.id)))
    box_candidates = box_q.all()

    radius_passing_ids: list = []
    for listing in box_candidates:
        item = db.get(CommunityItem, listing.item_id)
        owner_h = db.get(Household, item.household_id)
        owner_loc = _household_lat_lng(owner_h)
        if owner_loc is None:
            continue
        distance = _haversine_miles(viewer_lat, viewer_lng, owner_loc[0], owner_loc[1])
        effective = (
            listing.share_radius_miles
            if listing.share_radius_miles is not None
            else _household_default_radius(owner_h)
        )
        if distance <= effective:
            radius_passing_ids.append(listing.id)

    if radius_passing_ids:
        return base.filter(or_(community_exists, Listing.id.in_(radius_passing_ids)))
    return base.filter(community_exists)


def distance_for(viewer_household: Household, owner_household: Household) -> float | None:
    """Compute the rounded distance for a feed row's `distance_miles` field.
    Returns None when either household lacks a location."""
    v = _household_lat_lng(viewer_household)
    o = _household_lat_lng(owner_household)
    if v is None or o is None:
        return None
    return round(_haversine_miles(v[0], v[1], o[0], o[1]), 1)
```

- [ ] **Step 5: Run the visibility tests + full suite**

Run: `uv run pytest tests/test_community_visibility.py -v && uv run pytest -q`
Expected: 13 passed; full suite zero regressions.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/services/community/visibility.py \
  apps/backend/tests/conftest.py \
  apps/backend/tests/test_community_visibility.py
git commit -m "feat(community): visibility helper + cross-household isolation tests (security gate)"
```

---

### Task 7: Communities endpoints

**Files:**
- Modify: `apps/backend/app/routers/community.py`
- Test: `apps/backend/tests/test_community_communities_endpoints.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_community_communities_endpoints.py`:

```python
"""End-to-end tests for the community endpoints (create, preview, leave, mine)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_create_community_makes_caller_owner(client):
    resp = client.post(
        "/api/v1/community/communities",
        json={"slug": "test-1", "name": "Test 1", "description": "x"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["slug"] == "test-1"


def test_create_community_rejects_duplicate_slug(client):
    client.post("/api/v1/community/communities", json={"slug": "dup", "name": "A"})
    resp = client.post("/api/v1/community/communities", json={"slug": "dup", "name": "B"})
    assert resp.status_code == 409


def test_create_community_rejects_bad_slug(client):
    resp = client.post(
        "/api/v1/community/communities", json={"slug": "Bad Slug", "name": "x"},
    )
    assert resp.status_code == 422


def test_get_community_preview(client):
    client.post(
        "/api/v1/community/communities",
        json={"slug": "preview-1", "name": "Preview", "description": "hi"},
    )
    resp = client.get("/api/v1/community/communities/preview-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "preview-1"
    assert body["member_count"] == 1  # creator is owner
    assert body["your_membership_role"] == "owner"
    assert body["your_join_request_status"] is None


def test_get_unknown_community_returns_404(client):
    assert client.get("/api/v1/community/communities/nope").status_code == 404


def test_patch_community_as_owner(client):
    created = client.post(
        "/api/v1/community/communities",
        json={"slug": "pat-1", "name": "Old"},
    ).json()
    resp = client.patch(
        f"/api/v1/community/communities/{created['id']}",
        json={"name": "New", "description": "now"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"


def test_delete_community_soft_deletes(client):
    created = client.post(
        "/api/v1/community/communities",
        json={"slug": "del-1", "name": "Del"},
    ).json()
    resp = client.delete(f"/api/v1/community/communities/{created['id']}")
    assert resp.status_code == 200
    assert client.get("/api/v1/community/communities/del-1").status_code == 404


def test_get_my_communities(client):
    client.post("/api/v1/community/communities", json={"slug": "m1", "name": "M1"})
    client.post("/api/v1/community/communities", json={"slug": "m2", "name": "M2"})
    resp = client.get("/api/v1/community/communities/mine")
    assert resp.status_code == 200
    slugs = [m["community"]["slug"] for m in resp.json()["memberships"]]
    assert "m1" in slugs and "m2" in slugs


def test_leave_community_as_member(client):
    """Need a second user to demote; for the unit test we use the service layer to demote first."""
    created = client.post(
        "/api/v1/community/communities", json={"slug": "lv1", "name": "lv1"},
    ).json()
    from app.auth import DEV_USER_ID
    from app.db import SessionLocal
    from app.models.community import Community, CommunityMember
    with SessionLocal() as db:
        c = db.query(Community).filter_by(slug="lv1").one()
        # Add a second owner so the current user can leave without being sole owner.
        from app.models.core import User
        second = db.query(User).filter(User.email == "second@frugal-living.local").one()
        db.add(CommunityMember(community_id=c.id, user_id=second.id, role="owner"))
        db.commit()
    resp = client.post(f"/api/v1/community/communities/{created['id']}/leave")
    assert resp.status_code == 200
    # Caller is no longer a member.
    me = client.get("/api/v1/community/communities/mine").json()
    assert "lv1" not in [m["community"]["slug"] for m in me["memberships"]]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_community_communities_endpoints.py -v`
Expected: FAIL — endpoints don't exist yet (404 on first call).

- [ ] **Step 3: Add the endpoints to the community router**

In `apps/backend/app/routers/community.py`, add these imports alongside the existing ones (consolidate into the existing import block):

```python
from app.schemas.community import (
    # existing Phase 1 imports preserved …
    CommunityCreate,
    CommunityMembershipRead,
    CommunityPreview,
    CommunityRead,
    CommunityUpdate,
    MyCommunitiesResponse,
)
from app.services.community import communities as community_svc
from app.services.community.communities import (
    CommunityNotFound,
    CommunitySlugTaken,
    NotACommunityMember,
    SoleOwnerCannotLeave,
)
from app.models.community import Community, CommunityJoinRequest, CommunityMember
```

(Keep all the existing Phase 1 imports — only ADD the names above.)

Then append at the bottom of `apps/backend/app/routers/community.py`:

```python
@router.post("/communities", response_model=CommunityRead)
def create_community_endpoint(
    request: CommunityCreate,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> CommunityRead:
    """Create a community; the caller becomes its `owner`."""
    try:
        c = community_svc.create_community(
            db, creator_user=user, slug=request.slug,
            name=request.name, description=request.description,
        )
    except CommunitySlugTaken:
        raise HTTPException(status_code=409, detail="slug already in use") from None
    db.commit()
    db.refresh(c)
    return CommunityRead.model_validate(c)


@router.get("/communities/mine", response_model=MyCommunitiesResponse)
def my_communities_endpoint(
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> MyCommunitiesResponse:
    rows = community_svc.list_my_communities(db, user=user)
    return MyCommunitiesResponse(
        memberships=[
            CommunityMembershipRead(
                community=CommunityRead.model_validate(c),
                role=m.role,
                joined_at=m.joined_at,
            )
            for c, m in rows
        ]
    )


@router.get("/communities/{slug}", response_model=CommunityPreview)
def get_community_preview_endpoint(
    slug: str,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> CommunityPreview:
    """Preview a community by slug. 404 if not found. No member identities exposed."""
    c = community_svc.get_community_by_slug(db, slug)
    if c is None:
        raise HTTPException(status_code=404, detail="community not found")

    member_count = (
        db.query(CommunityMember).filter_by(community_id=c.id).count()
    )
    my_membership = (
        db.query(CommunityMember)
        .filter_by(community_id=c.id, user_id=user.id)
        .one_or_none()
    )
    my_role = my_membership.role if my_membership is not None else None
    my_request = (
        db.query(CommunityJoinRequest)
        .filter_by(community_id=c.id, user_id=user.id)
        .order_by(CommunityJoinRequest.requested_at.desc())
        .first()
    )
    my_status = my_request.status if my_request is not None else None
    return CommunityPreview(
        id=c.id, slug=c.slug, name=c.name, description=c.description,
        member_count=member_count,
        your_membership_role=my_role,
        your_join_request_status=my_status,
    )


@router.patch("/communities/{community_id}", response_model=CommunityRead)
def update_community_endpoint(
    community_id: uuid.UUID,
    request: CommunityUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> CommunityRead:
    try:
        c = community_svc.get_community_or_404(db, community_id)
        community_svc.update_community(
            db, owner_user=user, community=c,
            name=request.name, description=request.description,
        )
    except CommunityNotFound:
        raise HTTPException(status_code=404, detail="community not found") from None
    except NotACommunityMember:
        raise HTTPException(status_code=403, detail="must be a community owner") from None
    db.commit()
    db.refresh(c)
    return CommunityRead.model_validate(c)


@router.delete("/communities/{community_id}")
def delete_community_endpoint(
    community_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> dict:
    try:
        c = community_svc.get_community_or_404(db, community_id)
        community_svc.soft_delete_community(db, owner_user=user, community=c)
    except CommunityNotFound:
        raise HTTPException(status_code=404, detail="community not found") from None
    except NotACommunityMember:
        raise HTTPException(status_code=403, detail="must be a community owner") from None
    db.commit()
    return {"status": "deleted"}


@router.post("/communities/{community_id}/leave")
def leave_community_endpoint(
    community_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> dict:
    try:
        c = community_svc.get_community_or_404(db, community_id)
        community_svc.leave_community(db, user=user, community=c)
    except CommunityNotFound:
        raise HTTPException(status_code=404, detail="community not found") from None
    except NotACommunityMember:
        raise HTTPException(status_code=403, detail="not a member") from None
    except SoleOwnerCannotLeave:
        raise HTTPException(
            status_code=409, detail="sole owner — delete the community instead",
        ) from None
    db.commit()
    return {"status": "left"}
```

- [ ] **Step 4: Run the tests + full suite**

Run: `uv run pytest tests/test_community_communities_endpoints.py -v && uv run pytest -q`
Expected: 9 passed; full suite zero regressions.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/routers/community.py apps/backend/tests/test_community_communities_endpoints.py
git commit -m "feat(community): communities endpoints (create, preview, update, delete, leave, mine)"
```

---

### Task 8: Join-request endpoints

**Files:**
- Modify: `apps/backend/app/routers/community.py`
- Test: `apps/backend/tests/test_community_join_requests_endpoints.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_community_join_requests_endpoints.py`:

```python
"""End-to-end tests for the join-request endpoints. The DEV_USER_ID acts as the
community owner via the conftest auth override; a second seeded user requests
to join (created via the service layer for the test setup)."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import DEV_USER_ID
from app.db import SessionLocal
from app.main import app
from app.models.community import CommunityJoinRequest, CommunityMember
from app.models.core import User


@pytest.fixture
def client():
    return TestClient(app)


def _make_community(client, slug="js-1"):
    c = client.post(
        "/api/v1/community/communities", json={"slug": slug, "name": slug},
    ).json()
    return c


def _second_user():
    with SessionLocal() as db:
        return db.query(User).filter(User.email == "second@frugal-living.local").one()


def test_request_to_join_via_service_then_owner_lists_pending(client):
    c = _make_community(client, "js-2")
    # The conftest auth override makes the API caller the OWNER. A second user
    # requests via the service layer (the API would require their own session).
    second = _second_user()
    from app.services.community import communities as community_svc
    from app.services.community import join_requests as jr_svc
    with SessionLocal() as db:
        community = community_svc.get_community_or_404(db, uuid.UUID(c["id"]))
        jr_svc.request_to_join(db, user=db.get(User, second.id), community=community)
        db.commit()

    resp = client.get(f"/api/v1/community/communities/{c['id']}/join-requests")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"


def test_owner_approve_creates_membership(client):
    c = _make_community(client, "js-3")
    second = _second_user()
    from app.services.community import communities as community_svc
    from app.services.community import join_requests as jr_svc
    with SessionLocal() as db:
        community = community_svc.get_community_or_404(db, uuid.UUID(c["id"]))
        req = jr_svc.request_to_join(db, user=db.get(User, second.id), community=community)
        db.commit()
        req_id = req.id
    resp = client.post(
        f"/api/v1/community/communities/{c['id']}/join-requests/{req_id}/approve",
    )
    assert resp.status_code == 200
    with SessionLocal() as db:
        membership = db.query(CommunityMember).filter_by(
            community_id=uuid.UUID(c["id"]), user_id=second.id,
        ).one()
        assert membership.role == "member"


def test_approve_already_decided_returns_409(client):
    c = _make_community(client, "js-4")
    second = _second_user()
    from app.services.community import communities as community_svc
    from app.services.community import join_requests as jr_svc
    with SessionLocal() as db:
        community = community_svc.get_community_or_404(db, uuid.UUID(c["id"]))
        req = jr_svc.request_to_join(db, user=db.get(User, second.id), community=community)
        db.commit()
        req_id = req.id
    first = client.post(
        f"/api/v1/community/communities/{c['id']}/join-requests/{req_id}/approve",
    )
    assert first.status_code == 200
    second_call = client.post(
        f"/api/v1/community/communities/{c['id']}/join-requests/{req_id}/approve",
    )
    assert second_call.status_code == 409


def test_decline_request(client):
    c = _make_community(client, "js-5")
    second = _second_user()
    from app.services.community import communities as community_svc
    from app.services.community import join_requests as jr_svc
    with SessionLocal() as db:
        community = community_svc.get_community_or_404(db, uuid.UUID(c["id"]))
        req = jr_svc.request_to_join(db, user=db.get(User, second.id), community=community)
        db.commit()
        req_id = req.id
    resp = client.post(
        f"/api/v1/community/communities/{c['id']}/join-requests/{req_id}/decline",
        json={"note": "not yet"},
    )
    assert resp.status_code == 200
    with SessionLocal() as db:
        assert db.get(CommunityJoinRequest, req_id).status == "declined"


def test_self_request_via_endpoint_409_if_already_member(client):
    """The endpoint POST /join-requests asks the active user (the caller via the
    auth override) to request to join — but the caller is already the owner."""
    c = _make_community(client, "js-6")
    resp = client.post(f"/api/v1/community/communities/{c['id']}/join-requests")
    # Caller is already a member (owner) → 409.
    assert resp.status_code == 409
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_community_join_requests_endpoints.py -v`
Expected: FAIL.

- [ ] **Step 3: Add the endpoints**

In `apps/backend/app/routers/community.py`, extend the import block to include join-requests schemas and the service:

```python
from app.schemas.community import (
    # … existing …
    JoinRequestDecideRequest,
    JoinRequestRead,
)
from app.services.community import join_requests as jr_svc
from app.services.community.join_requests import (
    AlreadyAMember,
    AlreadyDecided,
    AlreadyPending,
    JoinRequestNotFound,
    get_request_or_404,
)
```

Then append:

```python
@router.post("/communities/{community_id}/join-requests", response_model=JoinRequestRead)
def request_to_join_endpoint(
    community_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> JoinRequestRead:
    try:
        c = community_svc.get_community_or_404(db, community_id)
        req = jr_svc.request_to_join(db, user=user, community=c)
    except CommunityNotFound:
        raise HTTPException(status_code=404, detail="community not found") from None
    except AlreadyAMember:
        raise HTTPException(status_code=409, detail="already a member") from None
    except AlreadyPending:
        raise HTTPException(status_code=409, detail="already have a pending request") from None
    db.commit()
    db.refresh(req)
    return JoinRequestRead.model_validate(req)


@router.post("/communities/{community_id}/join-requests/withdraw")
def withdraw_request_endpoint(
    community_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> dict:
    # Find the caller's own pending request for this community.
    req = (
        db.query(CommunityJoinRequest)
        .filter_by(community_id=community_id, user_id=user.id, status="pending")
        .one_or_none()
    )
    if req is None:
        raise HTTPException(status_code=404, detail="no pending request")
    try:
        jr_svc.withdraw_request(db, user=user, request=req)
    except (JoinRequestNotFound, AlreadyDecided) as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    db.commit()
    return {"status": "withdrawn"}


@router.get("/communities/{community_id}/join-requests", response_model=list[JoinRequestRead])
def list_join_requests_endpoint(
    community_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> list[JoinRequestRead]:
    try:
        c = community_svc.get_community_or_404(db, community_id)
        # Reuse the owner check from the service.
        community_svc._require_owner(db, user=user, community=c)
    except CommunityNotFound:
        raise HTTPException(status_code=404, detail="community not found") from None
    except NotACommunityMember:
        raise HTTPException(status_code=403, detail="must be a community owner") from None
    rows = jr_svc.list_pending_requests(db, community=c)
    return [JoinRequestRead.model_validate(r) for r in rows]


@router.post(
    "/communities/{community_id}/join-requests/{request_id}/approve",
    response_model=JoinRequestRead,
)
def approve_request_endpoint(
    community_id: uuid.UUID,
    request_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> JoinRequestRead:
    try:
        req = get_request_or_404(db, request_id)
        if req.community_id != community_id:
            raise JoinRequestNotFound(str(request_id))
        jr_svc.approve_request(db, owner_user=user, request=req)
    except JoinRequestNotFound:
        raise HTTPException(status_code=404, detail="join request not found") from None
    except NotACommunityMember:
        raise HTTPException(status_code=403, detail="must be a community owner") from None
    except AlreadyDecided:
        raise HTTPException(status_code=409, detail="already decided") from None
    db.commit()
    db.refresh(req)
    return JoinRequestRead.model_validate(req)


@router.post(
    "/communities/{community_id}/join-requests/{request_id}/decline",
    response_model=JoinRequestRead,
)
def decline_request_endpoint(
    community_id: uuid.UUID,
    request_id: uuid.UUID,
    request: JoinRequestDecideRequest,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> JoinRequestRead:
    try:
        req = get_request_or_404(db, request_id)
        if req.community_id != community_id:
            raise JoinRequestNotFound(str(request_id))
        jr_svc.decline_request(db, owner_user=user, request=req, note=request.note)
    except JoinRequestNotFound:
        raise HTTPException(status_code=404, detail="join request not found") from None
    except NotACommunityMember:
        raise HTTPException(status_code=403, detail="must be a community owner") from None
    except AlreadyDecided:
        raise HTTPException(status_code=409, detail="already decided") from None
    db.commit()
    db.refresh(req)
    return JoinRequestRead.model_validate(req)
```

- [ ] **Step 4: Run the tests + full suite**

Run: `uv run pytest tests/test_community_join_requests_endpoints.py -v && uv run pytest -q`
Expected: 5 passed; full suite zero regressions.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/routers/community.py apps/backend/tests/test_community_join_requests_endpoints.py
git commit -m "feat(community): join-request endpoints (request, withdraw, list, approve, decline)"
```

---

### Task 9: Listings endpoints

**Files:**
- Modify: `apps/backend/app/routers/community.py`
- Test: `apps/backend/tests/test_community_listings_endpoints.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_community_listings_endpoints.py`:

```python
"""End-to-end tests for listing endpoints."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _make_item(client, name="Drill", category="tools", quantity=1):
    return client.post(
        "/api/v1/community/items",
        json={"name": name, "category": category, "quantity": quantity},
    ).json()


def test_create_listing_basic(client):
    item = _make_item(client)
    resp = client.post(
        "/api/v1/community/listings",
        json={
            "item_id": item["id"],
            "allowed_exchange_types": ["borrow"],
            "quantity_available": 1,
            "community_ids": [],
            "share_in_radius": False,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["allowed_exchange_types"] == ["borrow"]
    assert body["item"]["name"] == "Drill"


def test_create_listing_rejects_quantity_too_high(client):
    item = _make_item(client, quantity=2)
    resp = client.post(
        "/api/v1/community/listings",
        json={
            "item_id": item["id"], "allowed_exchange_types": ["borrow"],
            "quantity_available": 5,  # > item.quantity
            "community_ids": [], "share_in_radius": False,
        },
    )
    assert resp.status_code == 422


def test_create_listing_rejects_unknown_item(client):
    resp = client.post(
        "/api/v1/community/listings",
        json={
            "item_id": str(uuid.uuid4()), "allowed_exchange_types": ["gift"],
            "quantity_available": 1, "community_ids": [], "share_in_radius": False,
        },
    )
    assert resp.status_code == 404


def test_list_mine(client):
    item = _make_item(client)
    client.post(
        "/api/v1/community/listings",
        json={
            "item_id": item["id"], "allowed_exchange_types": ["borrow"],
            "quantity_available": 1, "community_ids": [], "share_in_radius": False,
        },
    )
    resp = client.get("/api/v1/community/listings/mine")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_patch_listing(client):
    item = _make_item(client)
    created = client.post(
        "/api/v1/community/listings",
        json={
            "item_id": item["id"], "allowed_exchange_types": ["borrow"],
            "quantity_available": 1, "community_ids": [], "share_in_radius": False,
        },
    ).json()
    resp = client.patch(
        f"/api/v1/community/listings/{created['id']}",
        json={"availability_status": "paused"},
    )
    assert resp.status_code == 200
    assert resp.json()["availability_status"] == "paused"


def test_delete_listing(client):
    item = _make_item(client)
    created = client.post(
        "/api/v1/community/listings",
        json={
            "item_id": item["id"], "allowed_exchange_types": ["borrow"],
            "quantity_available": 1, "community_ids": [], "share_in_radius": False,
        },
    ).json()
    resp = client.delete(f"/api/v1/community/listings/{created['id']}")
    assert resp.status_code == 200
    assert client.get("/api/v1/community/listings/mine").json() == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_community_listings_endpoints.py -v`
Expected: FAIL — endpoints not mounted.

- [ ] **Step 3: Add the endpoints**

In `apps/backend/app/routers/community.py`, extend the import block:

```python
from app.schemas.community import (
    # … existing …
    ListingCreate,
    ListingItemSummary,
    ListingRead,
    ListingUpdate,
)
from app.services.community import listings as listings_svc
from app.services.community.listings import (
    CommunityNotPermittedForListing,
    ListingNotFound as _ListingNotFound,
    NotHouseholdMember,
    OneActiveListingPerItem,
    QuantityExceedsItem,
)
from app.models.community import Listing, ListingCommunity
```

Add a small helper to build the `ListingRead` payload for a household-owned listing:

```python
def _listing_read(db: Session, listing: Listing) -> ListingRead:
    item = db.get(CommunityItem, listing.item_id)
    assert item is not None
    community_ids = [
        lc.community_id for lc in
        db.query(ListingCommunity).filter_by(listing_id=listing.id).all()
    ]
    return ListingRead(
        id=listing.id,
        item=ListingItemSummary(
            id=item.id, name=item.name, category=item.category, tags=item.tags or [],
            quantity=item.quantity, condition=item.condition,
            estimated_value_usd=float(item.estimated_value_usd) if item.estimated_value_usd is not None else None,
            photo_url=item.photo_url, notes=item.notes,
        ),
        allowed_exchange_types=listing.allowed_exchange_types,
        quantity_available=listing.quantity_available,
        share_in_radius=listing.share_in_radius,
        share_radius_miles=listing.share_radius_miles,
        availability_status=listing.availability_status,
        description_override=listing.description_override,
        community_ids=community_ids,
        created_at=listing.created_at,
    )
```

Then append the endpoints:

```python
@router.post("/listings", response_model=ListingRead)
def create_listing_endpoint(
    request: ListingCreate,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ListingRead:
    try:
        listing = listings_svc.create_listing(
            db, household=household, user=user, item_id=request.item_id,
            allowed_exchange_types=request.allowed_exchange_types,
            quantity_available=request.quantity_available,
            community_ids=request.community_ids,
            share_in_radius=request.share_in_radius,
            share_radius_miles=request.share_radius_miles,
            description_override=request.description_override,
        )
    except _ListingNotFound:
        raise HTTPException(status_code=404, detail="item not found for your household") from None
    except QuantityExceedsItem as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    except CommunityNotPermittedForListing as e:
        raise HTTPException(status_code=403, detail=str(e)) from None
    except OneActiveListingPerItem:
        raise HTTPException(
            status_code=409, detail="an active listing already exists for this item",
        ) from None
    except NotHouseholdMember:
        raise HTTPException(status_code=403, detail="must be a household owner or member") from None
    db.commit()
    db.refresh(listing)
    return _listing_read(db, listing)


@router.get("/listings/mine", response_model=list[ListingRead])
def list_mine_endpoint(
    household: CurrentHousehold,
    db: Annotated[Session, Depends(get_db)],
) -> list[ListingRead]:
    rows = (
        db.query(Listing)
        .join(CommunityItem, CommunityItem.id == Listing.item_id)
        .filter(
            CommunityItem.household_id == household.id,
            Listing.deleted_at.is_(None),
        )
        .order_by(Listing.created_at.desc())
        .all()
    )
    return [_listing_read(db, r) for r in rows]


@router.patch("/listings/{listing_id}", response_model=ListingRead)
def update_listing_endpoint(
    listing_id: uuid.UUID,
    request: ListingUpdate,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ListingRead:
    try:
        listing = listings_svc.update_listing(
            db, household=household, user=user, listing_id=listing_id,
            allowed_exchange_types=request.allowed_exchange_types,
            quantity_available=request.quantity_available,
            community_ids=request.community_ids,
            share_in_radius=request.share_in_radius,
            share_radius_miles=request.share_radius_miles,
            description_override=request.description_override,
            availability_status=request.availability_status,
        )
    except _ListingNotFound:
        raise HTTPException(status_code=404, detail="listing not found") from None
    except QuantityExceedsItem as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    except CommunityNotPermittedForListing as e:
        raise HTTPException(status_code=403, detail=str(e)) from None
    except NotHouseholdMember:
        raise HTTPException(status_code=403, detail="must be a household owner or member") from None
    db.commit()
    db.refresh(listing)
    return _listing_read(db, listing)


@router.delete("/listings/{listing_id}")
def delete_listing_endpoint(
    listing_id: uuid.UUID,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    try:
        listings_svc.soft_delete_listing(
            db, household=household, user=user, listing_id=listing_id,
        )
    except _ListingNotFound:
        raise HTTPException(status_code=404, detail="listing not found") from None
    except NotHouseholdMember:
        raise HTTPException(status_code=403, detail="must be a household owner or member") from None
    db.commit()
    return {"status": "deleted"}


@router.get("/listings/{listing_id}", response_model=ListingRead)
def get_listing_endpoint(
    listing_id: uuid.UUID,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ListingRead:
    """Visibility-gated detail. Owners see their own; others see only listings
    the visibility helper returns."""
    listing = db.get(Listing, listing_id)
    if listing is None or listing.deleted_at is not None:
        raise HTTPException(status_code=404, detail="listing not found")
    item = db.get(CommunityItem, listing.item_id)
    if item is not None and item.household_id == household.id:
        # Owner-side read.
        return _listing_read(db, listing)
    # Visibility-gated read.
    from app.services.community.visibility import listings_visible_to
    visible_ids = {
        r.id for r in
        listings_visible_to(db, viewer_household=household, viewer_user=user).all()
    }
    if listing.id not in visible_ids:
        raise HTTPException(status_code=404, detail="listing not found")
    return _listing_read(db, listing)
```

- [ ] **Step 4: Run the tests + full suite**

Run: `uv run pytest tests/test_community_listings_endpoints.py -v && uv run pytest -q`
Expected: 6 passed; full suite zero regressions.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/routers/community.py apps/backend/tests/test_community_listings_endpoints.py
git commit -m "feat(community): listings endpoints (create, mine, get, patch, delete)"
```

---

### Task 10: Feed endpoint

**Files:**
- Modify: `apps/backend/app/routers/community.py`
- Test: `apps/backend/tests/test_community_feed_endpoint.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_community_feed_endpoint.py`:

```python
"""Feed endpoint — funnels through the visibility helper end-to-end."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.db import SessionLocal
from app.main import app
from app.models.community import CommunityMember
from app.models.core import Household, User


@pytest.fixture
def client():
    return TestClient(app)


def _make_listing_in_other_household_shared_to_caller():
    """Setup: the SECOND household creates an item + listing in a community
    that the FIRST household's user (the API caller) joins.
    Returns the listing id."""
    from app.services.community import communities as community_svc
    from app.services.community import items as items_svc
    from app.services.community import listings as listings_svc
    with SessionLocal() as db:
        first_user = db.get(User, DEV_USER_ID)
        second = db.query(User).filter(User.email == "second@frugal-living.local").one()
        second_household = db.query(Household).filter(Household.name == "Second Household").one()
        c = community_svc.create_community(
            db, creator_user=second, slug="feed-c", name="feed-c",
        )
        db.add(CommunityMember(community_id=c.id, user_id=first_user.id, role="member"))
        db.flush()
        item = items_svc.create_item(
            db, household=second_household, user=second, name="Borrowable Item", quantity=1,
        )
        listing = listings_svc.create_listing(
            db, household=second_household, user=second, item_id=item.id,
            allowed_exchange_types=["borrow"], quantity_available=1,
            community_ids=[c.id], share_in_radius=False,
        )
        db.commit()
        return listing.id


def test_feed_returns_shared_listing(client):
    listing_id = _make_listing_in_other_household_shared_to_caller()
    resp = client.get("/api/v1/community/feed")
    assert resp.status_code == 200
    body = resp.json()
    ids = [row["listing"]["id"] for row in body["rows"]]
    assert str(listing_id) in ids
    # And the row carries the matched_community_id (community path).
    for row in body["rows"]:
        if row["listing"]["id"] == str(listing_id):
            assert row["matched_community_id"] is not None
            assert row["distance_miles"] is None


def test_feed_does_not_return_own_household_listings(client):
    """Own household's listings never appear in the feed (visibility helper rule)."""
    # Create an item + listing for the caller's own household.
    item = client.post(
        "/api/v1/community/items", json={"name": "My Drill", "category": "tools"},
    ).json()
    client.post(
        "/api/v1/community/listings",
        json={
            "item_id": item["id"], "allowed_exchange_types": ["borrow"],
            "quantity_available": 1, "community_ids": [], "share_in_radius": False,
        },
    )
    resp = client.get("/api/v1/community/feed")
    assert resp.status_code == 200
    for row in resp.json()["rows"]:
        assert row["listing"]["item"]["name"] != "My Drill"


def test_feed_radius_match_includes_distance(client):
    """Set both households' locations; verify the row carries distance_miles."""
    from app.services.community import items as items_svc
    from app.services.community import listings as listings_svc
    from tests.conftest import set_household_location
    with SessionLocal() as db:
        first_h = db.get(Household, DEV_HOUSEHOLD_ID)
        second = db.query(User).filter(User.email == "second@frugal-living.local").one()
        second_household = db.query(Household).filter(Household.name == "Second Household").one()
        set_household_location(db, first_h, 40.6782, -73.9442)
        set_household_location(db, second_household, 40.6796, -73.9442)
        item = items_svc.create_item(
            db, household=second_household, user=second, name="Radius Item", quantity=1,
        )
        listings_svc.create_listing(
            db, household=second_household, user=second, item_id=item.id,
            allowed_exchange_types=["borrow"], quantity_available=1,
            community_ids=[], share_in_radius=True, share_radius_miles=5,
        )
        db.commit()
    resp = client.get("/api/v1/community/feed")
    assert resp.status_code == 200
    found = next(
        (r for r in resp.json()["rows"] if r["listing"]["item"]["name"] == "Radius Item"),
        None,
    )
    assert found is not None
    assert found["distance_miles"] is not None
    assert 0.0 <= found["distance_miles"] <= 1.0


def test_feed_filters_by_community_id(client):
    listing_id = _make_listing_in_other_household_shared_to_caller()
    # Get caller's communities; find the feed-c one
    mine = client.get("/api/v1/community/communities/mine").json()
    feed_c = next(m for m in mine["memberships"] if m["community"]["slug"] == "feed-c")
    resp = client.get(
        f"/api/v1/community/feed?community_id={feed_c['community']['id']}"
    )
    assert resp.status_code == 200
    ids = [r["listing"]["id"] for r in resp.json()["rows"]]
    assert str(listing_id) in ids


def test_feed_empty_when_caller_unconnected(client):
    resp = client.get("/api/v1/community/feed")
    assert resp.status_code == 200
    # No listings set up for this test → empty rows.
    assert resp.json()["rows"] == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_community_feed_endpoint.py -v`
Expected: FAIL — feed endpoint not implemented.

- [ ] **Step 3: Add the feed endpoint**

In `apps/backend/app/routers/community.py`, extend imports:

```python
from app.schemas.community import FeedResponse, FeedRow
from app.services.community.visibility import (
    distance_for,
    listings_visible_to,
)
```

Then append the endpoint:

```python
@router.get("/feed", response_model=FeedResponse)
def feed_endpoint(
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    community_id: Annotated[uuid.UUID | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    radius_miles_max: Annotated[int | None, Query(ge=1, le=500)] = None,
    cursor: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> FeedResponse:
    """The discovery feed. Every row's visibility was decided by
    `listings_visible_to(...)` — there is no other path for cross-household reads.
    Newest-first ordering; pagination is offset-based (opaque cursor)."""
    q = listings_visible_to(db, viewer_household=household, viewer_user=user)
    # Order by listing recency (newest first).
    q = q.order_by(Listing.created_at.desc())

    if category is not None:
        q = q.join(CommunityItem, CommunityItem.id == Listing.item_id).filter(
            CommunityItem.category == category
        )

    rows: list[FeedRow] = []
    fetched = q.offset(cursor).limit(limit + 1).all()
    has_more = len(fetched) > limit
    for listing in fetched[:limit]:
        item = db.get(CommunityItem, listing.item_id)
        if item is None:
            continue
        owner_h = db.get(Household, item.household_id)
        distance = distance_for(household, owner_h) if owner_h else None
        # Optional caller-side max-distance cap on radius rows.
        if (
            distance is not None
            and radius_miles_max is not None
            and distance > radius_miles_max
        ):
            continue

        # Did this row match via a shared community?
        community_match = None
        if community_id is not None:
            # If the caller filtered to a specific community, the match IS that one.
            community_match = community_id
        else:
            shared_membership = (
                db.query(CommunityMember.community_id)
                .join(ListingCommunity, ListingCommunity.community_id == CommunityMember.community_id)
                .filter(
                    ListingCommunity.listing_id == listing.id,
                    CommunityMember.user_id == user.id,
                )
                .first()
            )
            if shared_membership:
                community_match = shared_membership[0]

        rows.append(FeedRow(
            listing=_listing_read(db, listing),
            distance_miles=distance if listing.share_in_radius else None,
            matched_community_id=community_match,
        ))

    next_cursor = str(cursor + limit) if has_more else None
    # If caller filtered by community_id, narrow.
    if community_id is not None:
        rows = [
            r for r in rows
            if any(
                lc.community_id == community_id
                for lc in db.query(ListingCommunity).filter_by(listing_id=uuid.UUID(r.listing.id) if isinstance(r.listing.id, str) else r.listing.id).all()
            )
        ]

    return FeedResponse(rows=rows, next_cursor=next_cursor)
```

- [ ] **Step 4: Run the tests + full suite**

Run: `uv run pytest tests/test_community_feed_endpoint.py -v && uv run pytest -q`
Expected: 5 passed; full suite zero regressions.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/routers/community.py apps/backend/tests/test_community_feed_endpoint.py
git commit -m "feat(community): discovery feed endpoint via the visibility helper"
```

---

### Task 11: Frontend — types + api functions

**Files:**
- Modify: `apps/web/src/lib/types.ts`
- Modify: `apps/web/src/lib/api.ts`

- [ ] **Step 1: Append types**

In `apps/web/src/lib/types.ts`, append at the end:

```typescript
// ---------- Community Phase 2 ----------

export type ExchangeType = "borrow" | "swap" | "gift";
export type AvailabilityStatus = "available" | "paused" | "removed";
export type CommunityRole = "owner" | "member";
export type JoinRequestStatus = "pending" | "approved" | "declined" | "withdrawn";

export interface Community {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  created_at: string;
}

export interface CommunityPreview {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  member_count: number;
  your_membership_role: CommunityRole | null;
  your_join_request_status: JoinRequestStatus | null;
}

export interface CommunityMembership {
  community: Community;
  role: CommunityRole;
  joined_at: string;
}

export interface MyCommunitiesResponse {
  memberships: CommunityMembership[];
}

export interface JoinRequest {
  id: string;
  community_id: string;
  user_id: string;
  status: JoinRequestStatus;
  requested_at: string;
  decided_at: string | null;
  decision_note: string | null;
}

export interface ListingItemSummary {
  id: string;
  name: string;
  category: string;
  tags: string[];
  quantity: number;
  condition: string | null;
  estimated_value_usd: number | null;
  photo_url: string | null;
  notes: string | null;
}

export interface Listing {
  id: string;
  item: ListingItemSummary;
  allowed_exchange_types: ExchangeType[];
  quantity_available: number;
  share_in_radius: boolean;
  share_radius_miles: number | null;
  availability_status: AvailabilityStatus;
  description_override: string | null;
  community_ids: string[];
  created_at: string;
}

export interface FeedRow {
  listing: Listing;
  distance_miles: number | null;
  matched_community_id: string | null;
}

export interface FeedResponse {
  rows: FeedRow[];
  next_cursor: string | null;
}
```

- [ ] **Step 2: Append api functions**

In `apps/web/src/lib/api.ts`, add these names to the type-import block (alphabetically):

```typescript
  Community,
  CommunityMembership,
  CommunityPreview,
  CommunityRole,
  ExchangeType,
  FeedResponse,
  JoinRequest,
  Listing,
  MyCommunitiesResponse,
```

Append at the end of `apps/web/src/lib/api.ts`:

```typescript
// ---------- Community Phase 2 ----------

export function createCommunity(args: {
  slug: string; name: string; description?: string;
}): Promise<Community> {
  return api<Community>("/api/v1/community/communities", {
    method: "POST",
    body: JSON.stringify(args),
  });
}

export function getCommunityPreview(slug: string): Promise<CommunityPreview> {
  return api<CommunityPreview>(`/api/v1/community/communities/${encodeURIComponent(slug)}`);
}

export function updateCommunity(
  communityId: string,
  args: { name?: string; description?: string },
): Promise<Community> {
  return api<Community>(`/api/v1/community/communities/${communityId}`, {
    method: "PATCH",
    body: JSON.stringify(args),
  });
}

export function deleteCommunity(communityId: string): Promise<{ status: string }> {
  return api<{ status: string }>(`/api/v1/community/communities/${communityId}`, {
    method: "DELETE",
  });
}

export function leaveCommunity(communityId: string): Promise<{ status: string }> {
  return api<{ status: string }>(
    `/api/v1/community/communities/${communityId}/leave`,
    { method: "POST" },
  );
}

export function getMyCommunities(): Promise<MyCommunitiesResponse> {
  return api<MyCommunitiesResponse>("/api/v1/community/communities/mine");
}

export function requestToJoin(communityId: string): Promise<JoinRequest> {
  return api<JoinRequest>(
    `/api/v1/community/communities/${communityId}/join-requests`,
    { method: "POST" },
  );
}

export function withdrawJoinRequest(
  communityId: string,
): Promise<{ status: string }> {
  return api<{ status: string }>(
    `/api/v1/community/communities/${communityId}/join-requests/withdraw`,
    { method: "POST" },
  );
}

export function listJoinRequests(communityId: string): Promise<JoinRequest[]> {
  return api<JoinRequest[]>(
    `/api/v1/community/communities/${communityId}/join-requests`,
  );
}

export function approveJoinRequest(
  communityId: string,
  requestId: string,
): Promise<JoinRequest> {
  return api<JoinRequest>(
    `/api/v1/community/communities/${communityId}/join-requests/${requestId}/approve`,
    { method: "POST" },
  );
}

export function declineJoinRequest(
  communityId: string,
  requestId: string,
  note?: string,
): Promise<JoinRequest> {
  return api<JoinRequest>(
    `/api/v1/community/communities/${communityId}/join-requests/${requestId}/decline`,
    { method: "POST", body: JSON.stringify({ note: note ?? null }) },
  );
}

export function createListing(args: {
  item_id: string;
  allowed_exchange_types: ExchangeType[];
  quantity_available: number;
  community_ids?: string[];
  share_in_radius?: boolean;
  share_radius_miles?: number;
  description_override?: string;
}): Promise<Listing> {
  return api<Listing>("/api/v1/community/listings", {
    method: "POST",
    body: JSON.stringify({
      item_id: args.item_id,
      allowed_exchange_types: args.allowed_exchange_types,
      quantity_available: args.quantity_available,
      community_ids: args.community_ids ?? [],
      share_in_radius: args.share_in_radius ?? false,
      share_radius_miles: args.share_radius_miles,
      description_override: args.description_override,
    }),
  });
}

export function updateListing(
  listingId: string,
  patch: Partial<{
    allowed_exchange_types: ExchangeType[];
    quantity_available: number;
    community_ids: string[];
    share_in_radius: boolean;
    share_radius_miles: number;
    description_override: string;
    availability_status: "available" | "paused" | "removed";
  }>,
): Promise<Listing> {
  return api<Listing>(`/api/v1/community/listings/${listingId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function deleteListing(listingId: string): Promise<{ status: string }> {
  return api<{ status: string }>(`/api/v1/community/listings/${listingId}`, {
    method: "DELETE",
  });
}

export function listMyListings(): Promise<Listing[]> {
  return api<Listing[]>("/api/v1/community/listings/mine");
}

export function getListing(listingId: string): Promise<Listing> {
  return api<Listing>(`/api/v1/community/listings/${listingId}`);
}

export function getFeed(opts: {
  community_id?: string;
  category?: string;
  radius_miles_max?: number;
  cursor?: number;
  limit?: number;
} = {}): Promise<FeedResponse> {
  const params = new URLSearchParams();
  if (opts.community_id) params.set("community_id", opts.community_id);
  if (opts.category) params.set("category", opts.category);
  if (opts.radius_miles_max != null) params.set("radius_miles_max", String(opts.radius_miles_max));
  if (opts.cursor != null) params.set("cursor", String(opts.cursor));
  if (opts.limit != null) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return api<FeedResponse>(`/api/v1/community/feed${qs ? `?${qs}` : ""}`);
}
```

- [ ] **Step 3: Verify**

Run: `cd apps/web && pnpm typecheck`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/lib/types.ts apps/web/src/lib/api.ts
git commit -m "feat(community): phase 2 frontend types + api functions"
```

---

### Task 12: Frontend — `/communities` and `/communities/[slug]` pages

**Files:**
- Create: `apps/web/src/app/communities/page.tsx`
- Create: `apps/web/src/app/communities/[slug]/page.tsx`

- [ ] **Step 1: Create the index page**

Create `apps/web/src/app/communities/page.tsx`:

```tsx
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { createCommunity, getCommunityPreview, getMyCommunities, requestToJoin } from "@/lib/api";
import type { CommunityMembership, CommunityPreview } from "@/lib/types";

export default function CommunitiesPage() {
  const [memberships, setMemberships] = useState<CommunityMembership[]>([]);
  const [findSlug, setFindSlug] = useState("");
  const [preview, setPreview] = useState<CommunityPreview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // New community form
  const [newSlug, setNewSlug] = useState("");
  const [newName, setNewName] = useState("");

  async function refresh() {
    try {
      const r = await getMyCommunities();
      setMemberships(r.memberships);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function onFind(e: React.FormEvent) {
    e.preventDefault();
    setErr(null); setPreview(null);
    try {
      const p = await getCommunityPreview(findSlug.trim());
      setPreview(p);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  async function onRequest(communityId: string) {
    setBusy(true); setErr(null);
    try {
      await requestToJoin(communityId);
      const p = await getCommunityPreview(findSlug.trim());
      setPreview(p);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      await createCommunity({ slug: newSlug.trim(), name: newName.trim() });
      setNewSlug(""); setNewName("");
      await refresh();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <div className="min-h-screen px-6 py-10 md:px-12 max-w-4xl mx-auto">
      <header className="mb-10">
        <h1 className="text-3xl font-bold text-ink">Communities</h1>
        <p className="mt-1 text-stone-600">Groups your household shares items with.</p>
      </header>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-stone-900 mb-4">My communities</h2>
        {memberships.length === 0 ? (
          <p className="text-stone-500 text-sm">You haven&apos;t joined any communities yet.</p>
        ) : (
          <ul className="divide-y divide-stone-200 rounded-lg border border-stone-200 bg-white">
            {memberships.map((m) => (
              <li key={m.community.id} className="px-4 py-3">
                <Link
                  href={`/communities/${encodeURIComponent(m.community.slug)}`}
                  className="font-medium text-ink hover:text-clay"
                >
                  {m.community.name}
                </Link>
                <div className="text-xs text-stone-500 mt-0.5">
                  {m.role} · joined {new Date(m.joined_at).toLocaleDateString()}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="mb-12">
        <h2 className="text-xl font-semibold text-stone-900 mb-4">Find a community</h2>
        <form onSubmit={onFind} className="flex gap-2 mb-4">
          <input
            value={findSlug}
            onChange={(e) => setFindSlug(e.target.value)}
            placeholder="community-slug"
            className="flex-1 rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
          />
          <button
            type="submit"
            disabled={!findSlug.trim()}
            className="rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-paper disabled:opacity-50"
          >
            Look up
          </button>
        </form>
        {preview && (
          <div className="rounded-lg border border-stone-200 bg-white p-4">
            <div className="font-medium text-ink">{preview.name}</div>
            <div className="text-xs text-stone-500 mb-2">
              {preview.member_count} member{preview.member_count !== 1 && "s"}
            </div>
            {preview.description && <p className="text-sm text-stone-700 mb-3">{preview.description}</p>}
            {preview.your_membership_role ? (
              <Link
                href={`/communities/${encodeURIComponent(preview.slug)}`}
                className="text-sm text-clay underline"
              >
                You&apos;re already a {preview.your_membership_role}. Go to the community.
              </Link>
            ) : preview.your_join_request_status === "pending" ? (
              <p className="text-sm text-stone-500">Your request is pending.</p>
            ) : (
              <button
                onClick={() => onRequest(preview.id)}
                disabled={busy}
                className="rounded-lg bg-clay px-3 py-1.5 text-sm font-semibold text-paper disabled:opacity-50"
              >
                {busy ? "Requesting…" : "Request to join"}
              </button>
            )}
          </div>
        )}
      </section>

      <section>
        <h2 className="text-xl font-semibold text-stone-900 mb-4">Create a community</h2>
        <form onSubmit={onCreate} className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col">
            <label htmlFor="new-slug" className="text-xs text-stone-500 mb-1">Slug</label>
            <input
              id="new-slug" value={newSlug}
              onChange={(e) => setNewSlug(e.target.value)}
              placeholder="park-slope-tools"
              className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
            />
          </div>
          <div className="flex flex-col">
            <label htmlFor="new-name" className="text-xs text-stone-500 mb-1">Name</label>
            <input
              id="new-name" value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Park Slope Tools"
              className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
            />
          </div>
          <button
            type="submit"
            disabled={!newSlug.trim() || !newName.trim()}
            className="rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-paper disabled:opacity-50"
          >
            Create
          </button>
        </form>
      </section>

      {err && (
        <div className="mt-6 rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-800">
          {err}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Create the community detail page**

Create `apps/web/src/app/communities/[slug]/page.tsx`:

```tsx
"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  approveJoinRequest,
  declineJoinRequest,
  getCommunityPreview,
  leaveCommunity,
  listJoinRequests,
} from "@/lib/api";
import type { CommunityPreview, JoinRequest } from "@/lib/types";

export default function CommunityDetailPage() {
  const params = useParams<{ slug: string }>();
  const slug = params.slug;
  const [preview, setPreview] = useState<CommunityPreview | null>(null);
  const [requests, setRequests] = useState<JoinRequest[]>([]);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setErr(null);
    try {
      const p = await getCommunityPreview(slug);
      setPreview(p);
      if (p.your_membership_role === "owner") {
        const r = await listJoinRequests(p.id);
        setRequests(r);
      } else {
        setRequests([]);
      }
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  useEffect(() => {
    load();
  }, [slug]);

  async function onApprove(requestId: string) {
    if (!preview) return;
    await approveJoinRequest(preview.id, requestId);
    await load();
  }

  async function onDecline(requestId: string) {
    if (!preview) return;
    await declineJoinRequest(preview.id, requestId);
    await load();
  }

  async function onLeave() {
    if (!preview) return;
    if (!confirm("Leave this community?")) return;
    try {
      await leaveCommunity(preview.id);
      await load();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  if (!preview) {
    return <div className="px-6 py-10 text-stone-500">{err ?? "Loading…"}</div>;
  }

  return (
    <div className="min-h-screen px-6 py-10 md:px-12 max-w-4xl mx-auto">
      <header className="mb-8">
        <h1 className="text-3xl font-bold text-ink">{preview.name}</h1>
        <p className="text-xs text-stone-500 mt-1">
          {preview.member_count} member{preview.member_count !== 1 && "s"} ·{" "}
          {preview.your_membership_role ?? "not a member"}
        </p>
        {preview.description && (
          <p className="mt-3 text-stone-700">{preview.description}</p>
        )}
      </header>

      {preview.your_membership_role && (
        <button
          onClick={onLeave}
          className="rounded-md border border-stone-300 bg-white px-3 py-1.5 text-sm text-stone-700 hover:bg-stone-50 mb-8"
        >
          Leave community
        </button>
      )}

      {preview.your_membership_role === "owner" && (
        <section>
          <h2 className="text-xl font-semibold text-stone-900 mb-4">
            Pending join requests ({requests.length})
          </h2>
          {requests.length === 0 ? (
            <p className="text-stone-500 text-sm">No pending requests.</p>
          ) : (
            <ul className="divide-y divide-stone-200 rounded-lg border border-stone-200 bg-white">
              {requests.map((r) => (
                <li key={r.id} className="flex items-center justify-between px-4 py-3">
                  <div className="text-sm text-stone-700">
                    Request from <span className="font-mono">{r.user_id.slice(0, 8)}…</span>{" "}
                    on {new Date(r.requested_at).toLocaleDateString()}
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => onApprove(r.id)}
                      className="rounded-md bg-ink px-3 py-1 text-xs font-semibold text-paper"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => onDecline(r.id)}
                      className="rounded-md border border-stone-300 bg-white px-3 py-1 text-xs text-stone-700"
                    >
                      Decline
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {err && (
        <div className="mt-6 rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-800">
          {err}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Verify**

Run: `cd apps/web && pnpm typecheck`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/app/communities/
git commit -m "feat(community): /communities and /communities/[slug] pages"
```

---

### Task 13: Frontend — `/share` discovery feed page

**Files:**
- Create: `apps/web/src/app/share/page.tsx`

- [ ] **Step 1: Create the page**

Create `apps/web/src/app/share/page.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { getFeed, getMyCommunities } from "@/lib/api";
import type { CommunityMembership, FeedResponse } from "@/lib/types";

const CATEGORIES = [
  "all", "tools", "games", "books", "kitchen", "outdoor",
  "electronics", "furniture", "kids", "sports", "other",
] as const;

export default function SharePage() {
  const [feed, setFeed] = useState<FeedResponse | null>(null);
  const [memberships, setMemberships] = useState<CommunityMembership[]>([]);
  const [communityFilter, setCommunityFilter] = useState<string>("all");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setErr(null);
    try {
      const r = await getFeed({
        community_id: communityFilter === "all" ? undefined : communityFilter,
        category: categoryFilter === "all" ? undefined : categoryFilter,
      });
      setFeed(r);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  useEffect(() => {
    getMyCommunities().then((r) => setMemberships(r.memberships)).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [communityFilter, categoryFilter]);

  return (
    <div className="min-h-screen px-6 py-10 md:px-12 max-w-5xl mx-auto">
      <header className="mb-8">
        <h1 className="text-3xl font-bold text-ink">Share</h1>
        <p className="text-stone-600 mt-1">Items neighbors and community members have offered.</p>
      </header>

      <section className="mb-6 flex flex-wrap gap-3">
        <select
          value={communityFilter}
          onChange={(e) => setCommunityFilter(e.target.value)}
          className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
        >
          <option value="all">All communities + radius</option>
          {memberships.map((m) => (
            <option key={m.community.id} value={m.community.id}>
              {m.community.name}
            </option>
          ))}
        </select>
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
        >
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </section>

      {err && (
        <div className="mb-4 rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-800">
          {err}
        </div>
      )}

      {feed && feed.rows.length === 0 ? (
        <p className="text-stone-500 text-sm">Nothing visible yet. Join a community or set your location to see nearby items.</p>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2">
          {feed?.rows.map((row) => (
            <li key={row.listing.id} className="rounded-lg border border-stone-200 bg-white p-4">
              <div className="font-medium text-ink">{row.listing.item.name}</div>
              <div className="text-xs text-stone-500 mt-0.5">
                {row.listing.item.category} ·{" "}
                {row.listing.allowed_exchange_types.join(" · ")}
                {row.distance_miles != null && ` · ${row.distance_miles} mi away`}
              </div>
              {row.listing.description_override && (
                <p className="text-sm text-stone-700 mt-2">{row.listing.description_override}</p>
              )}
              {row.listing.item.condition && (
                <div className="text-xs text-stone-500 mt-1">
                  Condition: {row.listing.item.condition.replace("_", " ")}
                </div>
              )}
              <div className="text-xs text-stone-400 mt-2">
                Qty available: {row.listing.quantity_available}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify**

Run: `cd apps/web && pnpm typecheck`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/app/share/page.tsx
git commit -m "feat(community): /share discovery feed page"
```

---

### Task 14: Frontend — inventory Share button + listing form

**Files:**
- Modify: `apps/web/src/app/inventory/page.tsx`

- [ ] **Step 1: Extend the inventory page**

Read the current `apps/web/src/app/inventory/page.tsx` to locate the per-item list rendering block (the `<li>` for each inventory item). Add Share/Edit-sharing controls inline.

At the top of `apps/web/src/app/inventory/page.tsx`, extend the imports:

```typescript
import {
  captureInventory, createInventoryItem, deleteInventoryItem, fileToBase64,
  listInventory, createListing, deleteListing, getMyCommunities, listMyListings,
} from "@/lib/api";
import type {
  InventoryItem, ItemCategory, Listing, CommunityMembership, ExchangeType,
} from "@/lib/types";
```

Add three pieces of state inside `InventoryPage()`:

```typescript
  const [myListings, setMyListings] = useState<Listing[]>([]);
  const [memberships, setMemberships] = useState<CommunityMembership[]>([]);
  const [shareModal, setShareModal] = useState<InventoryItem | null>(null);
```

Extend `refresh()` (or add a parallel effect):

```typescript
  async function refreshAll() {
    try {
      const [items, listings, comms] = await Promise.all([
        listInventory(filter === "all" ? undefined : filter),
        listMyListings(),
        getMyCommunities(),
      ]);
      setItems(items);
      setMyListings(listings);
      setMemberships(comms.memberships);
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  }
```

Replace existing `refresh()` calls with `refreshAll()`, and replace the `[filter]` effect to call `refreshAll()`.

Inside each `<li>` (where items are rendered), add an action area before the Remove button:

```tsx
                <div className="flex items-center gap-2">
                  {myListings.some((l) => l.item.id === item.id) ? (
                    <span className="text-[11px] rounded-full bg-emerald-50 text-emerald-800 border border-emerald-200 px-2 py-0.5">
                      Shared
                    </span>
                  ) : (
                    <button
                      onClick={() => setShareModal(item)}
                      className="text-xs rounded-md border border-stone-300 bg-white px-2 py-1 text-stone-700 hover:bg-stone-50"
                    >
                      Share
                    </button>
                  )}
                  <button
                    onClick={() => handleDelete(item.id)}
                    className="text-xs text-stone-400 hover:text-red-600 transition"
                  >
                    Remove
                  </button>
                </div>
```

Then add the share modal at the bottom of the page JSX (before the closing `</div>`):

```tsx
      {shareModal && (
        <ShareModal
          item={shareModal}
          memberships={memberships}
          onClose={() => setShareModal(null)}
          onShared={async () => { setShareModal(null); await refreshAll(); }}
        />
      )}
```

And define `ShareModal` after the `InventoryPage` component (in the same file):

```tsx
function ShareModal({
  item, memberships, onClose, onShared,
}: {
  item: InventoryItem;
  memberships: CommunityMembership[];
  onClose: () => void;
  onShared: () => Promise<void>;
}) {
  const [types, setTypes] = useState<ExchangeType[]>(["borrow"]);
  const [quantity, setQuantity] = useState<number>(Math.min(1, item.quantity));
  const [selectedCommunities, setSelectedCommunities] = useState<Set<string>>(
    new Set(memberships.map((m) => m.community.id)),
  );
  const [shareInRadius, setShareInRadius] = useState<boolean>(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function toggleType(t: ExchangeType) {
    setTypes((prev) => prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]);
  }

  function toggleCommunity(id: string) {
    setSelectedCommunities((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      await createListing({
        item_id: item.id,
        allowed_exchange_types: types,
        quantity_available: quantity,
        community_ids: Array.from(selectedCommunities),
        share_in_radius: shareInRadius,
      });
      await onShared();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/40 px-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-xl font-semibold text-ink mb-1">Share &ldquo;{item.name}&rdquo;</h2>
        <p className="text-xs text-stone-500 mb-4">
          Choose who can see this and how you&apos;re willing to share.
        </p>

        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <div className="text-xs text-stone-500 mb-1">Offer for</div>
            <div className="flex gap-2 text-sm">
              {(["borrow", "swap", "gift"] as ExchangeType[]).map((t) => (
                <label key={t} className="inline-flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={types.includes(t)}
                    onChange={() => toggleType(t)}
                  />
                  {t}
                </label>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-xs text-stone-500 mb-1">Quantity available</label>
            <input
              type="number"
              min={1}
              max={item.quantity}
              value={quantity}
              onChange={(e) => setQuantity(Math.max(1, Math.min(item.quantity, Number(e.target.value))))}
              className="w-24 rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
            />
            <span className="ml-2 text-xs text-stone-500">of {item.quantity}</span>
          </div>

          {memberships.length > 0 && (
            <div>
              <div className="text-xs text-stone-500 mb-1">
                Visible in these communities (uncheck to exclude)
              </div>
              <div className="space-y-1">
                {memberships.map((m) => (
                  <label key={m.community.id} className="inline-flex items-center gap-1.5 mr-3 text-sm">
                    <input
                      type="checkbox"
                      checked={selectedCommunities.has(m.community.id)}
                      onChange={() => toggleCommunity(m.community.id)}
                    />
                    {m.community.name}
                  </label>
                ))}
              </div>
            </div>
          )}

          <div>
            <label className="inline-flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={shareInRadius}
                onChange={(e) => setShareInRadius(e.target.checked)}
              />
              Also share with households within ~5 miles of yours
            </label>
            <p className="ml-6 text-[11px] text-stone-500 mt-0.5">
              Off by default. Nearby households see distance only — never your exact address.
            </p>
          </div>

          {err && (
            <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-800">
              {err}
            </div>
          )}

          <div className="flex justify-end gap-2">
            <button
              type="button" onClick={onClose}
              className="rounded-md border border-stone-300 bg-white px-3 py-1.5 text-sm text-stone-700"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy || types.length === 0 || (selectedCommunities.size === 0 && !shareInRadius)}
              className="rounded-md bg-ink px-3 py-1.5 text-sm font-semibold text-paper disabled:opacity-50"
            >
              {busy ? "Sharing…" : "Share"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify**

Run: `cd apps/web && pnpm typecheck`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/app/inventory/page.tsx
git commit -m "feat(community): inventory Share button + listing creation modal"
```

---

### Task 15: Frontend — household location setup component

**Files:**
- Create: `apps/web/src/components/LocationSetup.tsx`
- Modify: `apps/web/src/app/share/page.tsx` (render the banner when location unset)
- Modify: `apps/web/src/lib/api.ts` (add a `setHouseholdLocation` call — see below)
- Modify: `apps/backend/app/routers/community.py` (add `POST /community/household/location`)
- Modify: `apps/backend/tests/test_community_communities_endpoints.py` (add a smoke test)

- [ ] **Step 1: Add the backend endpoint**

In `apps/backend/app/routers/community.py`, append:

```python
from pydantic import BaseModel as _BaseModel


class _HouseholdLocationRequest(_BaseModel):
    lat: float
    lng: float
    share_radius_miles: int | None = None


@router.post("/household/location")
def set_household_location_endpoint(
    request: _HouseholdLocationRequest,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Update the active household's lat/lng (stored in metadata_).
    Only the household owner/member may set this (`viewer` cannot)."""
    from app.services.community.listings import _require_household_member, NotHouseholdMember
    try:
        _require_household_member(db, user=user, household=household)
    except NotHouseholdMember:
        raise HTTPException(status_code=403, detail="must be a household owner or member") from None
    md = dict(household.metadata_ or {})
    md["lat"] = float(request.lat)
    md["lng"] = float(request.lng)
    if request.share_radius_miles is not None:
        md["share_radius_miles"] = int(request.share_radius_miles)
    household.metadata_ = md
    db.flush()
    db.commit()
    return {"status": "set"}
```

Add a smoke test at the end of `apps/backend/tests/test_community_communities_endpoints.py`:

```python
def test_set_household_location(client):
    resp = client.post(
        "/api/v1/community/household/location",
        json={"lat": 40.6782, "lng": -73.9442},
    )
    assert resp.status_code == 200
```

Run: `uv run pytest tests/test_community_communities_endpoints.py::test_set_household_location -v`
Expected: pass.

- [ ] **Step 2: Add the frontend api call**

Append to `apps/web/src/lib/api.ts`:

```typescript
export function setHouseholdLocation(args: {
  lat: number; lng: number; share_radius_miles?: number;
}): Promise<{ status: string }> {
  return api<{ status: string }>("/api/v1/community/household/location", {
    method: "POST",
    body: JSON.stringify(args),
  });
}
```

- [ ] **Step 3: Create the component**

Create `apps/web/src/components/LocationSetup.tsx`:

```tsx
"use client";

import { useState } from "react";
import { setHouseholdLocation } from "@/lib/api";

export default function LocationSetup({ onSaved }: { onSaved: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [manualLat, setManualLat] = useState("");
  const [manualLng, setManualLng] = useState("");
  const [showManual, setShowManual] = useState(false);

  async function useBrowserLocation() {
    if (!navigator.geolocation) {
      setShowManual(true);
      return;
    }
    setBusy(true); setErr(null);
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          await setHouseholdLocation({
            lat: pos.coords.latitude, lng: pos.coords.longitude,
          });
          onSaved();
        } catch (e) {
          setErr((e as Error).message);
        } finally {
          setBusy(false);
        }
      },
      () => {
        setShowManual(true);
        setBusy(false);
      },
      { enableHighAccuracy: false, timeout: 8000 },
    );
  }

  async function saveManual(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      await setHouseholdLocation({
        lat: parseFloat(manualLat), lng: parseFloat(manualLng),
      });
      onSaved();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm">
      <div className="font-medium text-amber-900 mb-1">Set your household&apos;s location</div>
      <p className="text-amber-800 mb-3">
        We use this only to compute distance to other households in your share radius.
        Nobody sees your exact address — only distance, rounded to the tenth of a mile.
      </p>
      <div className="flex flex-wrap gap-2">
        <button
          onClick={useBrowserLocation}
          disabled={busy}
          className="rounded-md bg-ink px-3 py-1.5 text-xs font-semibold text-paper disabled:opacity-50"
        >
          {busy ? "Detecting…" : "Use my browser location"}
        </button>
        <button
          onClick={() => setShowManual((v) => !v)}
          className="rounded-md border border-amber-300 bg-white px-3 py-1.5 text-xs text-amber-900"
        >
          Enter coordinates manually
        </button>
      </div>
      {showManual && (
        <form onSubmit={saveManual} className="mt-3 flex flex-wrap items-end gap-2">
          <label className="text-xs text-amber-900">
            Lat
            <input
              value={manualLat}
              onChange={(e) => setManualLat(e.target.value)}
              required step="0.0001" type="number"
              className="ml-1 w-28 rounded-md border border-amber-300 bg-white px-2 py-1 text-sm"
            />
          </label>
          <label className="text-xs text-amber-900">
            Lng
            <input
              value={manualLng}
              onChange={(e) => setManualLng(e.target.value)}
              required step="0.0001" type="number"
              className="ml-1 w-28 rounded-md border border-amber-300 bg-white px-2 py-1 text-sm"
            />
          </label>
          <button
            type="submit" disabled={busy || !manualLat || !manualLng}
            className="rounded-md bg-ink px-3 py-1 text-xs font-semibold text-paper disabled:opacity-50"
          >
            Save
          </button>
        </form>
      )}
      {err && <div className="mt-2 text-xs text-red-700">{err}</div>}
    </div>
  );
}
```

- [ ] **Step 4: Render the banner on `/share` when location is unset**

In `apps/web/src/app/share/page.tsx`, import:

```typescript
import LocationSetup from "@/components/LocationSetup";
import { useAuth } from "@/components/AuthProvider";
```

(Note: `useAuth` exposes `activeHousehold` but not its metadata. To know if location is set, the simplest is to attempt the feed and, if all rows lack `distance_miles`, infer the user might want to set location. Cleaner approach: fetch `/auth/me` and add a `household_has_location` derived flag.) For Phase 2 we keep it lightweight: always render the banner above the filters, with a small "dismiss" toggle in localStorage. Add at the top of the returned JSX:

```tsx
      {typeof window !== "undefined" && localStorage.getItem("hid_location_banner") !== "1" && (
        <div className="mb-6">
          <LocationSetup onSaved={() => {
            localStorage.setItem("hid_location_banner", "1");
            load();
          }} />
          <button
            onClick={() => {
              localStorage.setItem("hid_location_banner", "1");
              // Force re-render
              setFeed((f) => f && { ...f });
            }}
            className="mt-2 text-[11px] text-stone-500 underline"
          >
            Dismiss
          </button>
        </div>
      )}
```

- [ ] **Step 5: Verify**

Run: `cd apps/web && pnpm typecheck`
Expected: clean.

Run: `uv run pytest tests/test_community_communities_endpoints.py -v && uv run pytest -q`
Expected: 10 passed (was 9 + 1 new); full suite zero regressions.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/routers/community.py \
  apps/backend/tests/test_community_communities_endpoints.py \
  apps/web/src/lib/api.ts \
  apps/web/src/components/LocationSetup.tsx \
  apps/web/src/app/share/page.tsx
git commit -m "feat(community): household location setup (browser geolocation + manual fallback)"
```

---

### Task 16: Frontend — Sidebar Community section

**Files:**
- Modify: `apps/web/src/components/Sidebar.tsx`

- [ ] **Step 1: Add a Community section**

In `apps/web/src/components/Sidebar.tsx`, in the `SECTIONS` array, add a new section between the existing "Household" section and "Library":

```typescript
  {
    title: "Community",
    items: [
      { href: "/share", label: "Share" },
      { href: "/communities", label: "Communities" },
    ],
  },
```

- [ ] **Step 2: Verify**

Run: `cd apps/web && pnpm typecheck`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/Sidebar.tsx
git commit -m "feat(community): sidebar Community section (Share + Communities)"
```

---

### Task 17: Full verification

**Files:** none (verification only).

- [ ] **Step 1: Full backend suite**

Run: `cd apps/backend && uv run pytest -q`
Expected: zero failures. Approximate count: prior 243 + 5 (models) + 7 (schemas) + 7 (communities service) + 9 (join_requests service) + 10 (listings service) + 13 (visibility) + 10 (communities endpoints incl. location) + 5 (join_requests endpoints) + 6 (listings endpoints) + 5 (feed) = ~320 passed, 1 skipped.

- [ ] **Step 2: Ruff + mypy**

Run: `cd apps/backend && uv run ruff check . && uv run mypy app 2>&1 | tail -10`
Expected: ruff clean (run `uv run ruff check --fix .` if needed and amend the relevant commit). Mypy: only the 3 pre-existing errors in `app/config.py`, `app/db.py`, `app/services/ingredients.py` remain — no new errors in Phase 2 files (`app/models/community.py`, `app/services/community/*`, `app/routers/community.py`, `app/schemas/community.py`).

- [ ] **Step 3: Migration round-trip**

Run: `cd apps/backend && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: downgrade drops the 5 Phase 2 tables cleanly; upgrade recreates them.

- [ ] **Step 4: Frontend typecheck + build**

Run: `cd apps/web && pnpm typecheck && pnpm build`
Expected: typecheck clean; build succeeds. Routes list includes `/communities`, `/communities/[slug]`, `/share`.

- [ ] **Step 5: Smoke-test the running app (recommended)**

Run `./frugal up`. Sign up as user A → at `/communities`, create "test-1". Sign up as user B in another browser → look up "test-1" → request to join. As user A, approve. As user B, at `/inventory`, add a "Drill", click Share → pick "test-1" community → submit. As user A, at `/share`, see the drill in the feed. Both users set their household location via the banner; mark a listing `share_in_radius=true`; verify distance appears in the feed.

- [ ] **Step 6: Commit any lint/format fixes**

```bash
git add -A
git commit -m "chore(community): apply lint and format fixes"
```

(Skip if Steps 1–4 produced no changes.)

---

## Self-Review

**Spec coverage** — every section of `2026-05-24-tier-b-phase-2-community-listings-design.md` maps to a task:
- §2 decisions → encoded across §3-§4 of the spec which map to Tasks 1 (models), 2 (schemas), 6 (visibility helper).
- §3 visibility helper → Task 6 (helper + tests).
- §4 data model → Task 1 (models + migration 0005). `core.households.metadata_` lat/lng/share_radius_miles handled in Task 15 (location endpoint) and read in Task 6 (visibility).
- §5 sync rules → Task 5 (listings service + items.py cascade). Each rule has a dedicated test in `test_community_listings_service.py` (audit fixes #1 cascade, #7 quantity reconcile, #3 editor scope, #10 idempotent approve).
- §6 authorization → Tasks 5 (`_require_household_member`), 7 (`_require_owner` reuse), 9 (listing scope).
- §7 security & privacy → CSRF posture inherited (no new GET mutations); audit log writes in services (Tasks 3, 4, 5); slug-enumeration documented; distance rounded in Task 10 / Task 6 (`distance_for` rounds to 0.1).
- §8 API surface → Tasks 7 (communities), 8 (join requests), 9 (listings), 10 (feed), 15 (household location).
- §9 frontend → Tasks 11 (types/api), 12 (communities pages), 13 (feed page), 14 (inventory share), 15 (location), 16 (sidebar).
- §10 migration + no new deps → Task 1 (one Alembic migration); no new dependencies in any task.
- §11 test plan — cross-household isolation first-class → Task 6's `test_community_visibility.py` covers every documented case (community path, radius path, lister leaves, soft-deleted community, deactivated user, soft-deleted item, viewer's own household, paused listing). Concurrent approve idempotency in Task 4. Editor-scope test in Task 5.
- §12 out of scope items remain out of scope across all tasks.
- §13 plan-shape ordering — Tasks 1→17 follow it exactly; Task 6 (visibility helper + cross-household tests) lands before any cross-household endpoint (feed = Task 10).

**Placeholder scan** — no TBDs, no "implement appropriately," no "similar to Task N." Every step has the exact code or command needed.

**Type consistency** — `Community`, `CommunityMember`, `CommunityJoinRequest`, `Listing`, `ListingCommunity` (models, Task 1) are referenced with these exact names in Tasks 3, 4, 5, 6, 7, 8, 9, 10. Schemas `CommunityCreate`/`CommunityRead`/`CommunityPreview`/`MyCommunitiesResponse`/`JoinRequestRead`/`JoinRequestDecideRequest`/`ListingCreate`/`ListingUpdate`/`ListingRead`/`ListingItemSummary`/`FeedRow`/`FeedResponse` (Task 2) are used unchanged in Tasks 7–10. Service exceptions (`CommunityNotFound`, `CommunitySlugTaken`, `NotACommunityMember`, `SoleOwnerCannotLeave`, `JoinRequestNotFound`, `AlreadyPending`, `AlreadyAMember`, `AlreadyDecided`, `ListingNotFound`, `OneActiveListingPerItem`, `QuantityExceedsItem`, `CommunityNotPermittedForListing`, `NotHouseholdMember`) are caught with matching names in the router tasks. Frontend types (`Community`/`CommunityPreview`/`CommunityMembership`/`MyCommunitiesResponse`/`JoinRequest`/`ListingItemSummary`/`Listing`/`FeedRow`/`FeedResponse`/`ExchangeType`/`CommunityRole`/`AvailabilityStatus`/`JoinRequestStatus`) are defined in Task 11 and consumed unchanged in Tasks 12–16.
