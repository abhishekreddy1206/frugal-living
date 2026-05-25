from fastapi.testclient import TestClient

from app.auth import DEV_USER_ID
from app.db import SessionLocal
from app.main import app
from app.models.core import User
from tests.conftest import ADMIN_USER_ID

client = TestClient(app)


def test_list_users_admin(as_admin):
    r = client.get("/api/v1/admin/users?limit=200")
    assert r.status_code == 200
    emails = {row["email"] for row in r.json()}
    assert "admin@frugal-living.local" in emails
    assert "moderator@frugal-living.local" in emails


def test_list_users_moderator(as_moderator):
    r = client.get("/api/v1/admin/users")
    assert r.status_code == 200  # moderators can read user list


def test_list_users_regular_user_403():
    r = client.get("/api/v1/admin/users")
    assert r.status_code == 403


def test_get_user_detail(as_admin):
    r = client.get(f"/api/v1/admin/users/{DEV_USER_ID}")
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "dev@frugal-living.local"


def test_patch_role_admin_only(as_admin):
    r = client.patch(f"/api/v1/admin/users/{DEV_USER_ID}", json={"role": "moderator"})
    assert r.status_code == 200
    # Revert so other tests still see DEV_USER as 'user'
    client.patch(f"/api/v1/admin/users/{DEV_USER_ID}", json={"role": "user"})


def test_patch_role_moderator_blocked(as_moderator):
    r = client.patch(f"/api/v1/admin/users/{DEV_USER_ID}", json={"role": "moderator"})
    # Moderator cannot change roles — body shape requires admin
    assert r.status_code == 403


def test_patch_is_active_moderator_can(as_moderator):
    r = client.patch(
        f"/api/v1/admin/users/{DEV_USER_ID}",
        json={"is_active": False, "reason": "spam reports"},
    )
    assert r.status_code == 200
    # Revert
    client.patch(
        f"/api/v1/admin/users/{DEV_USER_ID}",
        json={"is_active": True, "reason": "appeal granted"},
    )


def test_patch_is_active_requires_reason(as_moderator):
    r = client.patch(f"/api/v1/admin/users/{DEV_USER_ID}", json={"is_active": False})
    assert r.status_code == 422  # reason missing


def test_patch_invalid_role_returns_422(as_admin):
    """Regression: invalid role value must surface as 422, not 500."""
    r = client.patch(f"/api/v1/admin/users/{DEV_USER_ID}", json={"role": "INVALID_ROLE"})
    assert r.status_code == 422


def test_last_admin_guard(as_admin):
    # Temporarily deactivate all other admins so ADMIN_USER is the only active admin.
    # This is necessary because the bootstrap test suite creates persisted admin rows.
    with SessionLocal() as db:
        other_admins = (
            db.query(User)
            .filter(User.id != ADMIN_USER_ID, User.role == "admin", User.is_active.is_(True))
            .all()
        )
        for u in other_admins:
            u.is_active = False
        db.commit()

    try:
        r = client.patch(f"/api/v1/admin/users/{ADMIN_USER_ID}", json={"role": "user"})
        assert r.status_code == 400
        assert "last active admin" in r.json()["detail"]
    finally:
        # Restore other admins so we don't poison later tests.
        with SessionLocal() as db:
            other_admins = (
                db.query(User)
                .filter(User.id != ADMIN_USER_ID, User.role == "admin", User.is_active.is_(False))
                .all()
            )
            for u in other_admins:
                u.is_active = True
            db.commit()


def test_lock_unlock_round_trip(as_moderator):
    r = client.post(
        f"/api/v1/admin/users/{DEV_USER_ID}/lock",
        json={"reason": "cool-off", "hours": 2},
    )
    assert r.status_code == 204
    r = client.get(f"/api/v1/admin/users/{DEV_USER_ID}")
    assert r.json()["locked_until"] is not None
    r = client.post(
        f"/api/v1/admin/users/{DEV_USER_ID}/unlock",
        json={"reason": "manual review passed"},
    )
    assert r.status_code == 204
    r = client.get(f"/api/v1/admin/users/{DEV_USER_ID}")
    assert r.json()["locked_until"] is None


def test_audit_log_written_on_lock(as_moderator, db):
    from app.models.core import AuditLog
    client.post(
        f"/api/v1/admin/users/{DEV_USER_ID}/lock",
        json={"reason": "test", "hours": 1},
    )
    rows = db.query(AuditLog).filter_by(action="admin.user.locked").all()
    assert any(r.payload.get("reason") == "test" for r in rows)


def test_search_by_email(as_admin):
    r = client.get("/api/v1/admin/users?q=moderator%40frugal-living.local")
    assert r.status_code == 200
    emails = {row["email"] for row in r.json()}
    assert "moderator@frugal-living.local" in emails
    assert "dev@frugal-living.local" not in emails
