"""Sweeps every admin-only endpoint: 401 unauthenticated, 403 user, 403 moderator, 200 admin."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

ADMIN_ONLY_GET_ENDPOINTS = [
    "/api/v1/admin/settings",
    "/api/v1/admin/settings/registry",
    "/api/v1/admin/flags",
]


@pytest.mark.parametrize("path", ADMIN_ONLY_GET_ENDPOINTS)
def test_unauthenticated_returns_401(path):
    from app.auth import get_current_user
    app.dependency_overrides.pop(get_current_user, None)
    r = client.get(path)
    assert r.status_code == 401, f"{path} returned {r.status_code}"


@pytest.mark.parametrize("path", ADMIN_ONLY_GET_ENDPOINTS)
def test_regular_user_returns_403(path):
    r = client.get(path)
    assert r.status_code == 403, f"{path} returned {r.status_code}"


@pytest.mark.parametrize("path", ADMIN_ONLY_GET_ENDPOINTS)
def test_moderator_returns_403(as_moderator, path):
    r = client.get(path)
    assert r.status_code == 403, f"{path} returned {r.status_code}"


@pytest.mark.parametrize("path", ADMIN_ONLY_GET_ENDPOINTS)
def test_admin_returns_200(as_admin, path):
    r = client.get(path)
    assert r.status_code == 200, f"{path} returned {r.status_code}"
