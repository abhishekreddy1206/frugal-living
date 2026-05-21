"""Pydantic request/response schemas for the content module."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CaptureRequest(BaseModel):
    """Capture a single piece of external content by URL."""

    url: str = Field(..., min_length=4)
    topic: str = "food"


class ContentItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    external_id: str
    title: str
    url: str | None
    author: str | None
    summary: str | None
    thumbnail_url: str | None
    topic: str
    tags: list[str]
    created_at: datetime


class FeedResponse(BaseModel):
    items: list[ContentItemRead]
    count: int
