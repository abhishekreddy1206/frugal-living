"""Pydantic schemas for settings endpoints."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class RegistryEntry(BaseModel):
    key: str
    type: str               # "bool" | "int" | "str" | "float"
    default: Any
    scopes: list[str]
    description: str
    public: bool


class SettingValueRead(BaseModel):
    key: str
    value: Any              # resolved value (or current at this layer)
    scope: str              # "global" | "household" | "user" | "default"
    scope_id: UUID | None = None


class SettingWrite(BaseModel):
    value: Any = Field(..., description="Type validated against the registry")


class GlobalSettingRow(BaseModel):
    key: str
    spec: RegistryEntry
    current_global: Any     # registry default if no override row exists
    has_global_override: bool
    household_override_count: int
    user_override_count: int


class SettingDetail(BaseModel):
    key: str
    spec: RegistryEntry
    current_global: Any
    has_global_override: bool
    household_overrides: list[dict]   # [{household_id, value, updated_at}]
    user_overrides: list[dict]        # [{user_id, value, updated_at}]
