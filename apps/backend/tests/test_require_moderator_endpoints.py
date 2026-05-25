"""Sweeps every moderator-allowed endpoint."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

MOD_OK_GET_ENDPOINTS = [
    "/api/v1/admin/users",
    "/api/v1/admin/communities",
    "/api/v1/admin/listings",
    "/api/v1/admin/audit-log",
]


@pytest.mark.parametrize("path", MOD_OK_GET_ENDPOINTS)
def test_regular_user_403(path):
    r = client.get(path)
    assert r.status_code == 403


@pytest.mark.parametrize("path", MOD_OK_GET_ENDPOINTS)
def test_moderator_200(as_moderator, path):
    r = client.get(path)
    assert r.status_code == 200


@pytest.mark.parametrize("path", MOD_OK_GET_ENDPOINTS)
def test_admin_200(as_admin, path):
    r = client.get(path)
    assert r.status_code == 200
