"""Service helpers for flag admin endpoints + the startup seeder."""
from __future__ import annotations

from sqlalchemy.orm import Session as DbSession

from app.models.core import AuditLog, FeatureFlag, FeatureFlagOverride, User

INITIAL_FLAGS: list[dict] = [
    {"key": "community.exchange_engine.enabled", "enabled_globally": False,
     "description": "Phase 3 exchange engine — dark launch"},
    {"key": "ai.opus_meal_planner.enabled", "enabled_globally": True,
     "description": "Kill-switch for Opus-backed meal planning"},
    {"key": "content.youtube_ingestion.enabled", "enabled_globally": True,
     "description": "Kill-switch for YouTube content enrichment"},
    {"key": "voice.assistant.enabled", "enabled_globally": False,
     "description": "Voice assistant launch gate"},
]


def seed_initial_flags(db: DbSession) -> None:
    """Idempotent seed of the initial flags. Safe to call on every startup."""
    for spec in INITIAL_FLAGS:
        exists = db.query(FeatureFlag).filter_by(key=spec["key"]).one_or_none()
        if exists is None:
            db.add(FeatureFlag(**spec))


def set_household_override(
    db: DbSession, *, flag_key: str, household_id, enabled: bool, actor: User,
) -> FeatureFlagOverride:
    row = (
        db.query(FeatureFlagOverride)
        .filter_by(flag_key=flag_key, household_id=household_id, user_id=None)
        .one_or_none()
    )
    if row is None:
        row = FeatureFlagOverride(
            flag_key=flag_key, household_id=household_id, enabled=enabled,
            created_by_user_id=actor.id,
        )
        db.add(row)
    else:
        row.enabled = enabled
    db.add(AuditLog(
        actor_user_id=actor.id, action="admin.flag.override_set",
        target_type="feature_flag", target_id=None,
        payload={"flag_key": flag_key, "household_id": str(household_id), "enabled": enabled},
    ))
    return row


def set_user_override(
    db: DbSession, *, flag_key: str, user_id, enabled: bool, actor: User,
) -> FeatureFlagOverride:
    row = (
        db.query(FeatureFlagOverride)
        .filter_by(flag_key=flag_key, user_id=user_id, household_id=None)
        .one_or_none()
    )
    if row is None:
        row = FeatureFlagOverride(
            flag_key=flag_key, user_id=user_id, enabled=enabled,
            created_by_user_id=actor.id,
        )
        db.add(row)
    else:
        row.enabled = enabled
    db.add(AuditLog(
        actor_user_id=actor.id, action="admin.flag.override_set",
        target_type="feature_flag", target_id=None,
        payload={"flag_key": flag_key, "user_id": str(user_id), "enabled": enabled},
    ))
    return row


def clear_household_override(db: DbSession, *, flag_key: str, household_id, actor: User) -> None:
    row = (
        db.query(FeatureFlagOverride)
        .filter_by(flag_key=flag_key, household_id=household_id, user_id=None)
        .one_or_none()
    )
    if row is not None:
        db.delete(row)
        db.add(AuditLog(
            actor_user_id=actor.id, action="admin.flag.override_cleared",
            target_type="feature_flag", target_id=None,
            payload={"flag_key": flag_key, "household_id": str(household_id)},
        ))


def clear_user_override(db: DbSession, *, flag_key: str, user_id, actor: User) -> None:
    row = (
        db.query(FeatureFlagOverride)
        .filter_by(flag_key=flag_key, user_id=user_id, household_id=None)
        .one_or_none()
    )
    if row is not None:
        db.delete(row)
        db.add(AuditLog(
            actor_user_id=actor.id, action="admin.flag.override_cleared",
            target_type="feature_flag", target_id=None,
            payload={"flag_key": flag_key, "user_id": str(user_id)},
        ))
