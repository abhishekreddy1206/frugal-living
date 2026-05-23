"""Tests for POST /auth/password."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models.core import (
    AuditLog,
    Household,
    HouseholdMember,
    Subscription,
    User,
)
from app.models.core import Session as DbSession

pytestmark = pytest.mark.real_auth


def _cleanup(email):
    with SessionLocal() as db:
        u = db.query(User).filter_by(email=email).one_or_none()
        if not u:
            return
        for row in db.query(AuditLog).filter_by(actor_user_id=u.id).all():
            db.delete(row)
        for s in db.query(DbSession).filter_by(user_id=u.id).all():
            db.delete(s)
        membership = db.query(HouseholdMember).filter_by(user_id=u.id).one_or_none()
        sub = db.query(Subscription).filter_by(user_id=u.id).one_or_none()
        if sub:
            db.delete(sub)
        if membership:
            h = db.get(Household, membership.household_id)
            db.delete(membership)
            if h:
                db.delete(h)
        db.delete(u)
        db.commit()


def test_password_change_requires_correct_current_password():
    c = TestClient(app)
    c.post("/api/v1/auth/signup", json={
        "email": "frank@example.com", "password": "hunter2hunter2",
        "display_name": "Frank", "household_name": "Frank",
    })
    try:
        bad = c.post("/api/v1/auth/password", json={
            "current_password": "wrong", "new_password": "new-password-123",
        })
        assert bad.status_code == 401
        ok = c.post("/api/v1/auth/password", json={
            "current_password": "hunter2hunter2", "new_password": "new-password-123",
        })
        assert ok.status_code == 200
        # Old password now fails on a new login
        c2 = TestClient(app)
        bad_login = c2.post("/api/v1/auth/login", json={
            "email": "frank@example.com", "password": "hunter2hunter2",
        })
        assert bad_login.status_code == 401
        good_login = c2.post("/api/v1/auth/login", json={
            "email": "frank@example.com", "password": "new-password-123",
        })
        assert good_login.status_code == 200
    finally:
        _cleanup("frank@example.com")


def test_password_change_revokes_other_sessions():
    c1 = TestClient(app)
    c1.post("/api/v1/auth/signup", json={
        "email": "gina@example.com", "password": "hunter2hunter2",
        "display_name": "Gina", "household_name": "Gina",
    })
    try:
        # Second device: log in to create another active session
        c2 = TestClient(app)
        c2.post("/api/v1/auth/login", json={
            "email": "gina@example.com", "password": "hunter2hunter2",
        })
        with SessionLocal() as db:
            u = db.query(User).filter_by(email="gina@example.com").one()
            assert db.query(DbSession).filter_by(user_id=u.id, revoked_at=None).count() == 2
        # Change password from c1 — c2's session should be revoked, c1's preserved
        c1.post("/api/v1/auth/password", json={
            "current_password": "hunter2hunter2", "new_password": "another-strong-pass",
        })
        with SessionLocal() as db:
            u = db.query(User).filter_by(email="gina@example.com").one()
            assert db.query(DbSession).filter_by(user_id=u.id, revoked_at=None).count() == 1
        # c1 still works, c2 is logged out
        assert c1.get("/api/v1/auth/me").status_code == 200
        assert c2.get("/api/v1/auth/me").status_code == 401
    finally:
        _cleanup("gina@example.com")
