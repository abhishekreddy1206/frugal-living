"""Resolver picks user > household > global > registry default, and validates types."""
import pytest

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.core import (
    AppSettingKv,
    HouseholdSetting,
    User,
    UserSetting,
)
from app.services.settings.resolver import clear_setting, get_setting, set_setting


def test_default_when_no_override(db):
    # `theme` has scopes=("user",) only; with no row, returns registry default
    user = db.get(User, DEV_USER_ID)
    assert get_setting(db, "theme", user=user) == "warm"


def test_user_override_takes_precedence(db):
    user = db.get(User, DEV_USER_ID)
    db.add(UserSetting(user_id=user.id, key="theme", value="muted"))
    db.flush()
    assert get_setting(db, "theme", user=user) == "muted"


def test_household_override_when_scope_includes_household(db):
    # `briefing_hour_local` is global+household+user; place a household value
    db.add(HouseholdSetting(household_id=DEV_HOUSEHOLD_ID, key="briefing_hour_local", value=9))
    db.flush()
    from app.models.core import Household
    hh = db.get(Household, DEV_HOUSEHOLD_ID)
    assert get_setting(db, "briefing_hour_local", household=hh) == 9


def test_user_beats_household_beats_global(db):
    user = db.get(User, DEV_USER_ID)
    from app.models.core import Household
    hh = db.get(Household, DEV_HOUSEHOLD_ID)
    db.add(AppSettingKv(key="briefing_hour_local", value=6))
    db.add(HouseholdSetting(household_id=hh.id, key="briefing_hour_local", value=9))
    db.add(UserSetting(user_id=user.id, key="briefing_hour_local", value=11))
    db.flush()
    assert get_setting(db, "briefing_hour_local", user=user, household=hh) == 11


def test_set_setting_rejects_wrong_type(db):
    user = db.get(User, DEV_USER_ID)
    with pytest.raises(ValueError, match="expects bool"):
        set_setting(db, "signups_open", "yes", scope="global", scope_id=None, actor=user)


def test_set_setting_rejects_bool_where_int_expected(db):
    user = db.get(User, DEV_USER_ID)
    with pytest.raises(ValueError, match="expects int"):
        set_setting(db, "llm_cli_concurrency", True, scope="global", scope_id=None, actor=user)


def test_set_setting_rejects_scope_not_in_registry(db):
    user = db.get(User, DEV_USER_ID)
    with pytest.raises(ValueError, match="not overridable at user scope"):
        set_setting(db, "signups_open", False, scope="user", scope_id=user.id, actor=user)


def test_coerce_falls_back_on_type_drift(db, caplog):
    user = db.get(User, DEV_USER_ID)
    # Write an int into a str-typed field directly (bypassing set_setting)
    db.add(UserSetting(user_id=user.id, key="theme", value=42))
    db.flush()
    import logging
    with caplog.at_level(logging.WARNING):
        val = get_setting(db, "theme", user=user)
    assert val == "warm"  # registry default
    assert any("theme" in r.message or "theme" in str(r.args) for r in caplog.records)


def test_set_setting_writes_audit_log(db):
    from app.models.core import AuditLog
    user = db.get(User, DEV_USER_ID)
    set_setting(db, "signups_open", False, scope="global", scope_id=None, actor=user)
    db.flush()
    rows = db.query(AuditLog).filter_by(action="admin.setting.set").all()
    assert any(r.payload.get("key") == "signups_open" for r in rows)


def test_unknown_key_raises(db):
    user = db.get(User, DEV_USER_ID)
    with pytest.raises(KeyError):
        get_setting(db, "nonexistent_key", user=user)


def test_clear_setting_writes_audit_log(db):
    from app.models.core import AuditLog
    user = db.get(User, DEV_USER_ID)
    # Seed a value, then clear it
    set_setting(db, "signups_open", False, scope="global", scope_id=None, actor=user)
    db.flush()
    clear_setting(db, "signups_open", scope="global", scope_id=None, actor=user)
    db.flush()
    rows = db.query(AuditLog).filter_by(action="admin.setting.cleared").all()
    assert any(r.payload.get("key") == "signups_open" for r in rows)


def test_clear_setting_noop_when_row_missing(db):
    from app.models.core import AuditLog
    user = db.get(User, DEV_USER_ID)
    before = db.query(AuditLog).filter_by(action="admin.setting.cleared").count()
    # Clearing a key that was never set must not raise and must not audit
    clear_setting(db, "theme", scope="user", scope_id=user.id, actor=user)
    db.flush()
    after = db.query(AuditLog).filter_by(action="admin.setting.cleared").count()
    assert after == before


def test_set_setting_rejects_unknown_scope_value(db):
    """A typo'd scope that happens to be in a multi-scope setting's tuple shouldn't slip."""
    user = db.get(User, DEV_USER_ID)
    with pytest.raises(ValueError, match="not overridable at typo scope|unknown scope"):
        # briefing_hour_local has all 3 scopes; "typo" isn't one of them
        set_setting(db, "briefing_hour_local", 9, scope="typo", scope_id=None, actor=user)
