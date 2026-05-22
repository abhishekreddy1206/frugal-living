"""Pydantic request/response schemas for the content module."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# A content topic maps to a tier (see ContentItem.topic). Constrain the request
# so a typo'd topic can't silently fragment the feed filter.
ContentTopic = Literal["food", "bills", "community", "general"]


class CaptureRequest(BaseModel):
    """Capture a single piece of external content by URL."""

    url: str = Field(..., min_length=4)
    topic: ContentTopic = "food"


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


class VideoIngredients(BaseModel):
    """LLM output — ingredients extracted from a video's text."""

    is_recipe_video: bool
    dish_name: str | None = None
    ingredients: list[str] = Field(default_factory=list)


class RecipeSuggestion(BaseModel):
    """A saved video ranked by pantry fit. Built by keyword in the router."""

    id: uuid.UUID
    provider: str
    external_id: str
    title: str
    url: str | None
    author: str | None
    thumbnail_url: str | None
    duration_seconds: int | None
    match_score: float
    matched_ingredients: list[str]
    match_reason: str


class RecipeSuggestionsResponse(BaseModel):
    suggestions: list[RecipeSuggestion]
    pantry_size: int


class EnrichResponse(BaseModel):
    enriched: int
    failed: int
    remaining: int
