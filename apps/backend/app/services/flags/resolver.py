"""Feature-flag resolver. user override > household override > enabled_globally > rollout > off."""
from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session as DbSession

from app.models.core import FeatureFlag, FeatureFlagOverride, Household, User


def is_enabled(
    db: DbSession,
    key: str,
    *,
    user: User | None = None,
    household: Household | None = None,
) -> bool:
    flag = (
        db.query(FeatureFlag)
        .filter(FeatureFlag.key == key, FeatureFlag.deleted_at.is_(None))
        .first()
    )
    if flag is None:
        return False

    # XOR check constraint already forbids rows with both columns set, but explicit
    # `.is_(None)` filters mirror the partial unique index predicates so the planner
    # uses them, and the intent is obvious in the query.
    if user:
        ov = (
            db.query(FeatureFlagOverride)
            .filter(
                FeatureFlagOverride.flag_key == key,
                FeatureFlagOverride.user_id == user.id,
                FeatureFlagOverride.household_id.is_(None),
            )
            .first()
        )
        if ov is not None:
            return ov.enabled

    if household:
        ov = (
            db.query(FeatureFlagOverride)
            .filter(
                FeatureFlagOverride.flag_key == key,
                FeatureFlagOverride.household_id == household.id,
                FeatureFlagOverride.user_id.is_(None),
            )
            .first()
        )
        if ov is not None:
            return ov.enabled

    if flag.enabled_globally:
        return True

    if flag.rollout_percent > 0 and user is not None:
        h = int(hashlib.sha256(f"{key}:{user.id}".encode()).hexdigest()[:8], 16)
        return (h % 100) < flag.rollout_percent

    return False
