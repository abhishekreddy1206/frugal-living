"""Admin settings endpoints — admin-only, all CRUD, all scopes."""
from fastapi.testclient import TestClient

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.main import app

client = TestClient(app)


def test_list_requires_admin(as_admin):
    r = client.get("/api/v1/admin/settings")
    assert r.status_code == 200
    keys = {row["key"] for row in r.json()}
    assert {"signups_open", "theme", "briefing_hour_local"} <= keys


def test_list_returns_override_counts(as_admin):
    from app.db import SessionLocal
    from app.models.core import HouseholdSetting, UserSetting
    with SessionLocal() as db_:
        db_.add(HouseholdSetting(household_id=DEV_HOUSEHOLD_ID, key="briefing_hour_local", value=9))
        db_.add(UserSetting(user_id=DEV_USER_ID, key="theme", value="muted"))
        db_.commit()
    r = client.get("/api/v1/admin/settings")
    rows = {row["key"]: row for row in r.json()}
    assert rows["briefing_hour_local"]["household_override_count"] == 1
    assert rows["theme"]["user_override_count"] == 1


def test_registry_endpoint(as_admin):
    r = client.get("/api/v1/admin/settings/registry")
    assert r.status_code == 200
    body = r.json()
    assert "signups_open" in body
    assert body["signups_open"]["type"] == "bool"


def test_set_global_then_get(as_admin):
    r = client.put("/api/v1/admin/settings/signups_open", json={"value": False})
    assert r.status_code == 204
    r = client.get("/api/v1/admin/settings/signups_open")
    assert r.status_code == 200
    body = r.json()
    assert body["current_global"] is False
    assert body["has_global_override"] is True


def test_set_global_type_mismatch_returns_422(as_admin):
    r = client.put("/api/v1/admin/settings/signups_open", json={"value": "yes"})
    assert r.status_code == 422


def test_set_household_override(as_admin):
    r = client.put(
        f"/api/v1/admin/settings/briefing_hour_local/household/{DEV_HOUSEHOLD_ID}",
        json={"value": 9},
    )
    assert r.status_code == 204
    r = client.get("/api/v1/admin/settings/briefing_hour_local")
    body = r.json()
    assert any(o["household_id"] == str(DEV_HOUSEHOLD_ID) and o["value"] == 9
               for o in body["household_overrides"])


def test_clear_global(as_admin):
    client.put("/api/v1/admin/settings/signups_open", json={"value": False})
    r = client.delete("/api/v1/admin/settings/signups_open")
    assert r.status_code == 204
    r = client.get("/api/v1/admin/settings/signups_open")
    body = r.json()
    assert body["has_global_override"] is False
    assert body["current_global"] is True  # registry default


def test_set_user_scoped_at_global_returns_422(as_admin):
    # `theme` is user-only; setting at global must fail
    r = client.put("/api/v1/admin/settings/theme", json={"value": "muted"})
    assert r.status_code == 422


def test_unknown_key_returns_404(as_admin):
    r = client.put("/api/v1/admin/settings/nonexistent", json={"value": 1})
    assert r.status_code == 404


def test_moderator_blocked():
    # Override to moderator; admin-only endpoint must 403
    from app.auth import get_current_user
    from app.main import app as _app
    from tests.conftest import MODERATOR_USER_ID, _override_as
    _app.dependency_overrides[get_current_user] = _override_as(MODERATOR_USER_ID)
    try:
        r = client.get("/api/v1/admin/settings")
        assert r.status_code == 403
    finally:
        _app.dependency_overrides.pop(get_current_user, None)


def test_unauthenticated_returns_401():
    from app.auth import get_current_user
    from app.main import app as _app
    # Remove the autouse override
    _app.dependency_overrides.pop(get_current_user, None)
    r = client.get("/api/v1/admin/settings")
    assert r.status_code == 401
