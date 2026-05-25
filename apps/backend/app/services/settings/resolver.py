"""Resolver: get_setting(user/hh/global/default), set_setting(scope), with type checks."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session as DbSession

from app.models.core import (
    AppSettingKv,
    AuditLog,
    Household,
    HouseholdSetting,
    User,
    UserSetting,
)
from app.services.settings.registry import SETTING_REGISTRY, Scope, SettingSpec

logger = logging.getLogger(__name__)


def _coerce(value: Any, spec: SettingSpec, *, key: str) -> Any:
    """Type-check JSONB-decoded value. Return default + log on mismatch (fail-closed)."""
    if isinstance(value, spec.type) and not (spec.type is int and isinstance(value, bool)):
        return value
    logger.warning(
        "setting %s has type %s, expected %s; falling back to default",
        key, type(value).__name__, spec.type.__name__,
    )
    return spec.default


def get_setting(
    db: DbSession,
    key: str,
    *,
    user: User | None = None,
    household: Household | None = None,
) -> Any:
    """Resolve a setting value: user → household → global → registry default."""
    spec = SETTING_REGISTRY[key]  # KeyError on unknown key (programmer bug)

    if user and "user" in spec.scopes:
        row = db.get(UserSetting, (user.id, key))
        if row is not None:
            return _coerce(row.value, spec, key=key)

    if household and "household" in spec.scopes:
        row = db.get(HouseholdSetting, (household.id, key))
        if row is not None:
            return _coerce(row.value, spec, key=key)

    row = db.get(AppSettingKv, key)
    if row is not None:
        return _coerce(row.value, spec, key=key)

    return spec.default


def set_setting(
    db: DbSession,
    key: str,
    value: Any,
    *,
    scope: Scope,
    scope_id: uuid.UUID | None,
    actor: User,
) -> None:
    """Upsert a setting at the given scope. Writes audit log. Caller commits."""
    spec = SETTING_REGISTRY[key]
    if scope not in spec.scopes:
        raise ValueError(f"{key} is not overridable at {scope} scope")
    if spec.type is int and isinstance(value, bool):
        raise ValueError(f"{key} expects {spec.type.__name__}, got bool")
    if not isinstance(value, spec.type):
        raise ValueError(f"{key} expects {spec.type.__name__}, got {type(value).__name__}")

    if scope == "global":
        row = db.get(AppSettingKv, key)
        if row is None:
            db.add(AppSettingKv(key=key, value=value, updated_by_user_id=actor.id))
        else:
            row.value = value
            row.updated_by_user_id = actor.id
    elif scope == "household":
        assert scope_id is not None
        row = db.get(HouseholdSetting, (scope_id, key))
        if row is None:
            db.add(HouseholdSetting(
                household_id=scope_id, key=key, value=value,
                updated_by_user_id=actor.id,
            ))
        else:
            row.value = value
            row.updated_by_user_id = actor.id
    elif scope == "user":
        assert scope_id is not None
        row = db.get(UserSetting, (scope_id, key))
        if row is None:
            db.add(UserSetting(user_id=scope_id, key=key, value=value))
        else:
            row.value = value
            # UserSetting has no updated_by_user_id column; the actor is in the AuditLog row.
    else:
        # Defensive: the registry check above guards against unknown scopes when the
        # registry agrees they're not allowed, but a typo'd scope that *happens* to be
        # in a multi-scope setting's `scopes` tuple would slip through silently. Catching
        # it here keeps the audit log honest (no "I set it" entry when no row was written).
        raise ValueError(f"unknown scope: {scope}")

    # NOTE: if sensitive settings are ever added to the registry, filter or redact
    # the value here before logging.
    db.add(AuditLog(
        actor_user_id=actor.id,
        action="admin.setting.set",
        target_type="setting",
        target_id=None,
        payload={
            "key": key, "scope": scope,
            "scope_id": str(scope_id) if scope_id else None,
            "value": value,
        },
    ))


def clear_setting(
    db: DbSession,
    key: str,
    *,
    scope: Scope,
    scope_id: uuid.UUID | None,
    actor: User,
) -> None:
    """Delete a setting at the given scope (returns to next-layer-down resolution).

    No-ops silently when the row doesn't exist — clearing an unset key is harmless.
    """
    _ = SETTING_REGISTRY[key]  # KeyError on unknown key (programmer bug)
    if scope == "global":
        row = db.get(AppSettingKv, key)
    elif scope == "household":
        assert scope_id is not None
        row = db.get(HouseholdSetting, (scope_id, key))
    elif scope == "user":
        assert scope_id is not None
        row = db.get(UserSetting, (scope_id, key))
    else:
        raise ValueError(f"unknown scope: {scope}")

    if row is not None:
        db.delete(row)
        db.add(AuditLog(
            actor_user_id=actor.id,
            action="admin.setting.cleared",
            target_type="setting",
            target_id=None,
            payload={"key": key, "scope": scope, "scope_id": str(scope_id) if scope_id else None},
        ))
