from fastapi.testclient import TestClient

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.main import app

client = TestClient(app)


def test_list_includes_seeded_flags(as_admin):
    r = client.get("/api/v1/admin/flags")
    assert r.status_code == 200
    keys = {row["key"] for row in r.json()}
    assert "community.exchange_engine.enabled" in keys
    assert "ai.opus_meal_planner.enabled" in keys


def test_create_flag(as_admin):
    r = client.post("/api/v1/admin/flags", json={
        "key": "test.new_flag", "description": "x", "enabled_globally": True,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["key"] == "test.new_flag"
    assert body["enabled_globally"] is True


def test_create_flag_duplicate_returns_409(as_admin):
    client.post("/api/v1/admin/flags", json={"key": "dup.flag"})
    r = client.post("/api/v1/admin/flags", json={"key": "dup.flag"})
    assert r.status_code == 409


def test_patch_flag(as_admin):
    client.post("/api/v1/admin/flags", json={"key": "patch.flag"})
    r = client.patch("/api/v1/admin/flags/patch.flag", json={
        "enabled_globally": True, "rollout_percent": 25,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["enabled_globally"] is True
    assert body["rollout_percent"] == 25


def test_soft_delete_flag(as_admin):
    client.post("/api/v1/admin/flags", json={"key": "delete.flag"})
    r = client.delete("/api/v1/admin/flags/delete.flag")
    assert r.status_code == 204
    # Re-fetch — flag is gone from list (deleted_at filter)
    r = client.get("/api/v1/admin/flags")
    keys = {row["key"] for row in r.json()}
    assert "delete.flag" not in keys


def test_set_household_override(as_admin):
    client.post("/api/v1/admin/flags", json={"key": "hh.over"})
    r = client.put(
        f"/api/v1/admin/flags/hh.over/household/{DEV_HOUSEHOLD_ID}",
        json={"enabled": True},
    )
    assert r.status_code == 204
    r = client.get("/api/v1/admin/flags/hh.over")
    body = r.json()
    assert any(o["household_id"] == str(DEV_HOUSEHOLD_ID) and o["enabled"] is True
               for o in body["household_overrides"])


def test_set_user_override(as_admin):
    client.post("/api/v1/admin/flags", json={"key": "u.over"})
    r = client.put(
        f"/api/v1/admin/flags/u.over/user/{DEV_USER_ID}",
        json={"enabled": True},
    )
    assert r.status_code == 204


def test_clear_household_override(as_admin):
    client.post("/api/v1/admin/flags", json={"key": "clear.hh"})
    client.put(
        f"/api/v1/admin/flags/clear.hh/household/{DEV_HOUSEHOLD_ID}",
        json={"enabled": True},
    )
    r = client.delete(f"/api/v1/admin/flags/clear.hh/household/{DEV_HOUSEHOLD_ID}")
    assert r.status_code == 204


def test_moderator_blocked():
    from app.auth import get_current_user
    from app.main import app as _app
    from tests.conftest import MODERATOR_USER_ID, _override_as
    _app.dependency_overrides[get_current_user] = _override_as(MODERATOR_USER_ID)
    try:
        r = client.get("/api/v1/admin/flags")
        assert r.status_code == 403
    finally:
        _app.dependency_overrides.pop(get_current_user, None)
