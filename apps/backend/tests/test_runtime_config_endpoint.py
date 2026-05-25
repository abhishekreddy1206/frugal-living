from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_runtime_config_is_public():
    # Remove the autouse override to simulate unauthenticated
    from app.auth import get_current_user
    app.dependency_overrides.pop(get_current_user, None)
    r = client.get("/api/v1/runtime-config")
    assert r.status_code == 200


def test_runtime_config_returns_only_public_keys(as_admin):
    r = client.get("/api/v1/runtime-config")
    body = r.json()
    # signups_open and maintenance_message are public
    assert "signups_open" in body
    assert "maintenance_message" in body
    # llm_cli_concurrency is not public
    assert "llm_cli_concurrency" not in body
    # theme is user-scoped, not global+public
    assert "theme" not in body


def test_runtime_config_reflects_global_setting(as_admin):
    client.put("/api/v1/admin/settings/signups_open", json={"value": False})
    r = client.get("/api/v1/runtime-config")
    assert r.json()["signups_open"] is False
