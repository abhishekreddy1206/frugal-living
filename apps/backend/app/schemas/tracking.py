"""Pydantic schemas for the tracking tier."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class StreakRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: str  # cooked_from_pantry | zero_waste_week | meal_planned_week
    current_length: int
    longest_length: int
    last_event_on: date | None


class BadgeAwardRead(BaseModel):
    """Awarded badge with its definition merged in."""

    key: str
    name: str
    description: str | None
    awarded_at: datetime
    icon_url: str | None
