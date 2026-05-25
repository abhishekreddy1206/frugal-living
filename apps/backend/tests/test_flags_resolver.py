"""is_enabled: user > household > global > rollout_percent > default off."""
from datetime import UTC

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.core import (
    FeatureFlag,
    FeatureFlagOverride,
    Household,
    User,
)
from app.services.flags.resolver import is_enabled


def _flag(db, key, *, enabled_globally=False, rollout=0):
    db.add(FeatureFlag(key=key, enabled_globally=enabled_globally, rollout_percent=rollout))
    db.flush()


def test_unknown_flag_returns_false(db):
    user = db.get(User, DEV_USER_ID)
    assert is_enabled(db, "nonexistent", user=user) is False


def test_global_enabled(db):
    user = db.get(User, DEV_USER_ID)
    _flag(db, "ff.simple", enabled_globally=True)
    assert is_enabled(db, "ff.simple", user=user) is True


def test_user_override_beats_global(db):
    user = db.get(User, DEV_USER_ID)
    _flag(db, "ff.user_off", enabled_globally=True)
    db.add(FeatureFlagOverride(flag_key="ff.user_off", user_id=user.id, enabled=False))
    db.flush()
    assert is_enabled(db, "ff.user_off", user=user) is False


def test_household_override_beats_global(db):
    hh = db.get(Household, DEV_HOUSEHOLD_ID)
    _flag(db, "ff.hh_on", enabled_globally=False)
    db.add(FeatureFlagOverride(flag_key="ff.hh_on", household_id=hh.id, enabled=True))
    db.flush()
    assert is_enabled(db, "ff.hh_on", household=hh) is True


def test_user_override_beats_household_override(db):
    user = db.get(User, DEV_USER_ID)
    hh = db.get(Household, DEV_HOUSEHOLD_ID)
    _flag(db, "ff.stack")
    db.add(FeatureFlagOverride(flag_key="ff.stack", household_id=hh.id, enabled=True))
    db.add(FeatureFlagOverride(flag_key="ff.stack", user_id=user.id, enabled=False))
    db.flush()
    assert is_enabled(db, "ff.stack", user=user, household=hh) is False


def test_rollout_percent_is_deterministic(db):
    user = db.get(User, DEV_USER_ID)
    _flag(db, "ff.rolling", enabled_globally=False, rollout=50)
    a = is_enabled(db, "ff.rolling", user=user)
    b = is_enabled(db, "ff.rolling", user=user)
    assert a == b


def test_rollout_zero_is_off(db):
    user = db.get(User, DEV_USER_ID)
    _flag(db, "ff.zero", enabled_globally=False, rollout=0)
    assert is_enabled(db, "ff.zero", user=user) is False


def test_rollout_100_is_on(db):
    user = db.get(User, DEV_USER_ID)
    _flag(db, "ff.full", enabled_globally=False, rollout=100)
    assert is_enabled(db, "ff.full", user=user) is True


def test_rollout_ignored_without_user(db):
    _flag(db, "ff.anon", enabled_globally=False, rollout=100)
    assert is_enabled(db, "ff.anon") is False  # no user, rollout ignored


def test_deleted_flag_returns_false(db):
    from datetime import datetime
    user = db.get(User, DEV_USER_ID)
    db.add(FeatureFlag(
        key="ff.gone", enabled_globally=True,
        deleted_at=datetime.now(UTC),
    ))
    db.flush()
    assert is_enabled(db, "ff.gone", user=user) is False
