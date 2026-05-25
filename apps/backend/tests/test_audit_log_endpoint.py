from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.auth import DEV_USER_ID
from app.db import SessionLocal
from app.main import app
from app.models.core import AuditLog

client = TestClient(app)


def _seed_audit(*, action, days_ago=0):
    with SessionLocal() as db_:
        db_.add(AuditLog(
            actor_user_id=DEV_USER_ID,
            action=action, target_type="x", target_id=None, payload={},
            created_at=datetime.now(UTC) - timedelta(days=days_ago),
        ))
        db_.commit()


def test_admin_can_read(as_admin):
    _seed_audit(action="admin.test.write")
    r = client.get("/api/v1/admin/audit-log")
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_moderator_can_read(as_moderator):
    _seed_audit(action="admin.test.mod_read")
    r = client.get("/api/v1/admin/audit-log")
    assert r.status_code == 200


def test_regular_user_403():
    r = client.get("/api/v1/admin/audit-log")
    assert r.status_code == 403


def test_filter_by_action(as_admin):
    _seed_audit(action="admin.user.locked")
    _seed_audit(action="admin.flag.updated")
    r = client.get("/api/v1/admin/audit-log?action=admin.user.locked")
    rows = r.json()
    # All returned rows must match the filter
    assert all(row["action"] == "admin.user.locked" for row in rows)


def test_filter_by_action_prefix(as_admin):
    _seed_audit(action="admin.user.locked")
    _seed_audit(action="admin.user.unlocked")
    _seed_audit(action="admin.flag.updated")
    r = client.get("/api/v1/admin/audit-log?action_prefix=admin.user")
    actions = {row["action"] for row in r.json()}
    # The prefix filter excludes flag-updates
    assert "admin.flag.updated" not in actions
    assert {"admin.user.locked", "admin.user.unlocked"} <= actions


def test_pagination(as_admin):
    for i in range(5):
        _seed_audit(action=f"admin.test.p{i}")
    r = client.get("/api/v1/admin/audit-log?limit=2&offset=0")
    assert len(r.json()) == 2
