from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class FeatureFlagRead(BaseModel):
    key: str
    description: str | None
    enabled_globally: bool
    rollout_percent: int
    household_override_count: int = 0
    user_override_count: int = 0


class FeatureFlagCreate(BaseModel):
    key: str = Field(..., min_length=3, max_length=120)
    description: str | None = None
    enabled_globally: bool = False
    rollout_percent: int = Field(0, ge=0, le=100)


class FeatureFlagPatch(BaseModel):
    description: str | None = None
    enabled_globally: bool | None = None
    rollout_percent: int | None = Field(None, ge=0, le=100)


class OverrideWrite(BaseModel):
    enabled: bool


class OverrideRead(BaseModel):
    id: UUID
    flag_key: str
    household_id: UUID | None
    user_id: UUID | None
    enabled: bool
    created_at: datetime
