"""Setting registry — source of truth for what settings exist, their types,
their defaults, and which scopes may override them."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

Scope = str  # "global" | "household" | "user"


@dataclass(frozen=True)
class SettingSpec:
    type: type
    default: Any
    scopes: tuple[Scope, ...]
    description: str
    public: bool = False  # exposed via /api/v1/runtime-config when True


SETTING_REGISTRY: dict[str, SettingSpec] = {
    # --- Operator-only globals ---
    "signups_open": SettingSpec(
        type=bool, default=True, scopes=("global",),
        description="Allow new account signups", public=True,
    ),
    "maintenance_message": SettingSpec(
        type=str, default="", scopes=("global",),
        description="Public banner shown across all pages; empty = no banner",
        public=True,
    ),
    "llm_cli_concurrency": SettingSpec(
        type=int, default=4, scopes=("global",),
        description="Max in-flight Claude CLI subprocess calls",
    ),

    # --- Cascadable defaults ---
    "default_ai_model": SettingSpec(
        type=str, default="sonnet", scopes=("global", "household"),
        description="Default Claude model for new AI calls",
    ),
    "briefing_hour_local": SettingSpec(
        type=int, default=7, scopes=("global", "household", "user"),
        description="Local hour (0-23) when daily briefings are generated",
    ),
    "pantry_expiry_warn_days": SettingSpec(
        type=int, default=3, scopes=("global", "household"),
        description="Warn N days before pantry items expire",
    ),

    # --- User-only preferences ---
    "theme": SettingSpec(
        type=str, default="warm", scopes=("user",),
        description="UI theme: 'warm' | 'muted'",
    ),
    "email_notifications": SettingSpec(
        type=bool, default=True, scopes=("user",),
        description="Receive email notifications",
    ),
}
