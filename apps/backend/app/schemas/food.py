"""Pydantic request/response schemas for the food tier."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

# ---------- Pantry capture ----------

class PantryCaptureRequest(BaseModel):
    """Photo-to-pantry input. Image arrives as base64 (not persisted in v1)."""

    image_base64: str = Field(..., min_length=32, description="Base64-encoded image data")
    media_type: str = Field(default="image/jpeg", pattern=r"^image/(jpeg|jpg|png|webp|heic)$")
    location_id: uuid.UUID | None = Field(
        default=None, description="Which pantry location these items belong to"
    )


class ExtractedItem(BaseModel):
    """A single item the vision model extracted from a photo, pre-persistence."""

    raw_name: str = Field(..., min_length=1, max_length=200)
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=32)
    confidence: float = Field(..., ge=0.0, le=1.0)
    suggested_expires_at: date | None = None
    notes: str | None = Field(default=None, max_length=500)


class ExtractedPantry(BaseModel):
    """Full structured response from extract_pantry_from_image."""

    items: list[ExtractedItem]


class PantryItemRead(BaseModel):
    """Persisted pantry item, returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    raw_name: str
    ingredient_id: uuid.UUID | None
    location_id: uuid.UUID | None
    quantity: float | None
    unit: str | None
    purchased_at: date | None
    opened_at: date | None
    expires_at: date | None
    estimated_value: float | None
    source: str
    confidence: float | None
    photo_url: str | None
    notes: str | None
    created_at: datetime


class PantryCaptureResponse(BaseModel):
    items: list[PantryItemRead]
    created_count: int
