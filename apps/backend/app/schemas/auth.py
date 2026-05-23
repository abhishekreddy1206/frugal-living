"""Auth-tier request/response schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=200)
    display_name: str = Field(..., min_length=1, max_length=120)
    household_name: str = Field(..., min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=200)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=200)
    new_password: str = Field(..., min_length=8, max_length=200)


class CreateHouseholdRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class SwitchHouseholdRequest(BaseModel):
    household_id: uuid.UUID


class CreateInviteRequest(BaseModel):
    role: str = Field(default="member", pattern=r"^(member|viewer)$")
    email: str | None = Field(default=None, max_length=320)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    display_name: str | None


class HouseholdRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str


class MembershipRead(BaseModel):
    household: HouseholdRead
    role: str


class MeResponse(BaseModel):
    user: UserRead
    memberships: list[MembershipRead]
    active_household: HouseholdRead | None


class SignupResponse(BaseModel):
    user: UserRead
    household: HouseholdRead


class LoginResponse(BaseModel):
    user: UserRead
    active_household: HouseholdRead


class InvitePreview(BaseModel):
    household_name: str
    role: str
    inviter_name: str | None
    expires_at: datetime


class CreateInviteResponse(BaseModel):
    token: str  # raw token (one-time return)
    url: str    # /invite/<token>
    expires_at: datetime
