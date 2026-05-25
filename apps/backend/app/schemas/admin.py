"""Pydantic schemas shared across admin endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ModerationReason(BaseModel):
    """Mixin for moderator-grade writes — every such write requires a non-empty reason."""
    reason: str = Field(..., min_length=3, max_length=500)


class UserListRow(BaseModel):
    id: UUID
    email: str
    display_name: str | None
    role: str
    is_active: bool
    locked_until: datetime | None
    created_at: datetime


class UserDetail(UserListRow):
    household_memberships: list[dict]
    listing_count: int = 0


class RolePatch(BaseModel):
    role: Literal["user", "moderator", "admin"]


class IsActivePatch(ModerationReason):
    is_active: bool


class LockBody(ModerationReason):
    hours: int = Field(..., ge=1, le=720)  # 1 hour to 30 days
