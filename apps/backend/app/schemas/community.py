"""Community-tier (Tier B) request/response schemas. Phase 1: inventory."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

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
