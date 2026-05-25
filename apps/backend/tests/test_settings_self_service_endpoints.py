from fastapi.testclient import TestClient

from app.auth import DEV_HOUSEHOLD_ID
from app.main import app

client = TestClient(app)


def test_get_my_settings_returns_only_user_scoped_keys():
    r = client.get("/api/v1/me/settings")
    assert r.status_code == 200
    body = r.json()
    keys = {row["key"] for row in body}
    # theme + email_notifications + briefing_hour_local are all user-scoped
    assert {"theme", "email_notifications", "briefing_hour_local"} <= keys
    # signups_open is global-only — must NOT appear
    assert "signups_open" not in keys


def test_set_my_setting():
    r = client.put("/api/v1/me/settings/theme", json={"value": "muted"})
    assert r.status_code == 204
    r = client.get("/api/v1/me/settings")
    rows = {row["key"]: row["value"] for row in r.json()}
    assert rows["theme"] == "muted"


def test_clear_my_setting():
    client.put("/api/v1/me/settings/theme", json={"value": "muted"})
    r = client.delete("/api/v1/me/settings/theme")
    assert r.status_code == 204
    r = client.get("/api/v1/me/settings")
    rows = {row["key"]: row["value"] for row in r.json()}
    assert rows["theme"] == "warm"  # registry default


def test_set_non_user_scoped_key_returns_422():
    r = client.put("/api/v1/me/settings/signups_open", json={"value": False})
    assert r.status_code == 422


def test_household_settings_member_can_read():
    r = client.get(f"/api/v1/households/{DEV_HOUSEHOLD_ID}/settings")
    assert r.status_code == 200


def test_household_settings_owner_can_write():
    r = client.put(
        f"/api/v1/households/{DEV_HOUSEHOLD_ID}/settings/briefing_hour_local",
        json={"value": 9},
    )
    assert r.status_code == 204


def test_household_settings_non_member_returns_403(second_household):
    # DEV user isn't a member of second_household — write must 403
    r = client.put(
        f"/api/v1/households/{second_household.id}/settings/briefing_hour_local",
        json={"value": 9},
    )
    assert r.status_code == 403
