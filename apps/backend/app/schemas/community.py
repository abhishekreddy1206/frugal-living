"""Community-tier (Tier B) request/response schemas. Phase 1: inventory."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

ITEM_CATEGORIES = [
    "tools", "games", "books", "kitchen", "outdoor",
    "electronics", "furniture", "kids", "sports", "other",
]
_CATEGORY_PATTERN = "^(" + "|".join(ITEM_CATEGORIES) + ")$"

ITEM_CONDITIONS = ["new", "like_new", "good", "fair", "poor"]
_CONDITION_PATTERN = "^(" + "|".join(ITEM_CONDITIONS) + ")$"


class ItemCreate(BaseModel):
    """Manual item creation — category/condition are strictly validated."""

    name: str = Field(..., min_length=1, max_length=200)
    category: str = Field(default="other", pattern=_CATEGORY_PATTERN)
    tags: list[str] = Field(default_factory=list)
    quantity: int = Field(default=1, ge=1)
    condition: str | None = Field(default=None, pattern=_CONDITION_PATTERN)
    estimated_value_usd: float | None = Field(default=None, ge=0)
    location: str | None = Field(default=None, max_length=120)
    acquired_on: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ItemUpdate(BaseModel):
    """Partial update — every field optional; absent means "leave unchanged"."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, pattern=_CATEGORY_PATTERN)
    tags: list[str] | None = None
    quantity: int | None = Field(default=None, ge=1)
    condition: str | None = Field(default=None, pattern=_CONDITION_PATTERN)
    estimated_value_usd: float | None = Field(default=None, ge=0)
    location: str | None = Field(default=None, max_length=120)
    acquired_on: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ItemRead(BaseModel):
    """Persisted inventory item, returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: str
    tags: list[str]
    quantity: int
    condition: str | None
    estimated_value_usd: float | None
    location: str | None
    acquired_on: date | None
    photo_url: str | None
    source: str
    confidence: float | None
    notes: str | None
    created_at: datetime


class ExtractedInventoryItem(BaseModel):
    """One item the vision model extracted, pre-persistence.

    Permissive — parsed straight from untrusted LLM output, so `category` and
    `condition` are plain strings the service layer coerces to valid values.
    """

    name: str = Field(..., min_length=1, max_length=200)
    category: str = "other"
    tags: list[str] = Field(default_factory=list)
    quantity: int | None = Field(default=1, ge=1)
    condition: str | None = None
    estimated_value_usd: float | None = Field(default=None, ge=0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    notes: str | None = Field(default=None, max_length=500)


class ExtractedInventory(BaseModel):
    """Full structured response from extract_items_from_image."""

    items: list[ExtractedInventoryItem]


class ItemCaptureRequest(BaseModel):
    """Photo-to-inventory input. Image arrives as base64 (not persisted in v1)."""

    image_base64: str = Field(..., min_length=32, description="Base64-encoded image data")
    media_type: str = Field(
        default="image/jpeg", pattern=r"^image/(jpeg|jpg|png|webp|heic)$"
    )


class ItemCaptureResponse(BaseModel):
    items: list[ItemRead]
    created_count: int


# ---------- Phase 2: communities & listings ----------

import uuid as _uuid  # noqa: E402 — kept local to the Phase 2 block for clarity
from datetime import datetime as _datetime  # noqa: E402

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
    # the listing's picks (visible to anyone with access to the listing)
    community_ids: list[_uuid.UUID]
    created_at: _datetime


class FeedRow(BaseModel):
    """One row in the discovery feed. Excludes lat/lng — distance is rounded."""
    listing: ListingRead
    distance_miles: float | None  # set when matched via radius path; otherwise null
    matched_community_id: _uuid.UUID | None  # set when matched via community path; otherwise null


class FeedResponse(BaseModel):
    rows: list[FeedRow]
    next_cursor: str | None  # opaque pagination cursor; null when no more pages
