"""Tests for POST /auth/login (and login throttling)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models.core import Household, HouseholdMember, Subscription, User

pytestmark = pytest.mark.real_auth


@pytest.fixture
def client():
    return TestClient(app)


def _signup(client, email="dana@example.com", password="hunter2hunter2"):
    return client.post("/api/v1/auth/signup", json={
        "email": email, "password": password,
        "display_name": "Dana", "household_name": "Dana",
    })


def _cleanup(email):
    with SessionLocal() as db:
        u = db.query(User).filter_by(email=email).one_or_none()
        if not u:
            return
        # FK order: audit_log -> sessions -> membership/subscription -> household -> user
        from app.models.core import AuditLog
        for row in db.query(AuditLog).filter_by(actor_user_id=u.id).all():
            db.delete(row)
        from app.models.core import Session as DbSession
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


def test_login_with_correct_credentials_sets_session_cookie(client):
    _signup(client)
    try:
        # Use a fresh client (no cookie carried from signup).
        c2 = TestClient(app)
        resp = c2.post("/api/v1/auth/login", json={
            "email": "dana@example.com", "password": "hunter2hunter2",
        })
        assert resp.status_code == 200, resp.text
        assert settings.session_cookie_name in resp.cookies
    finally:
        _cleanup("dana@example.com")


def test_login_with_wrong_password_returns_401(client):
    _signup(client)
    try:
        c2 = TestClient(app)
        resp = c2.post("/api/v1/auth/login", json={
            "email": "dana@example.com", "password": "wrong",
        })
        assert resp.status_code == 401
    finally:
        _cleanup("dana@example.com")


def test_login_with_unknown_email_returns_401(client):
    c2 = TestClient(app)
    resp = c2.post("/api/v1/auth/login", json={
        "email": "nobody@example.com", "password": "whatever",
    })
    assert resp.status_code == 401


def test_login_locks_after_threshold_failures(client):
    _signup(client)
    try:
        c2 = TestClient(app)
        # Default threshold is 5
        for _ in range(settings.login_lockout_threshold):
            c2.post("/api/v1/auth/login", json={
                "email": "dana@example.com", "password": "wrong",
            })
        # Even with correct password, locked
        resp = c2.post("/api/v1/auth/login", json={
            "email": "dana@example.com", "password": "hunter2hunter2",
        })
        assert resp.status_code == 429
    finally:
        _cleanup("dana@example.com")


def test_successful_login_resets_failed_count(client):
    _signup(client)
    try:
        c2 = TestClient(app)
        c2.post("/api/v1/auth/login", json={
            "email": "dana@example.com", "password": "wrong",
        })
        c2.post("/api/v1/auth/login", json={
            "email": "dana@example.com", "password": "wrong",
        })
        resp = c2.post("/api/v1/auth/login", json={
            "email": "dana@example.com", "password": "hunter2hunter2",
        })
        assert resp.status_code == 200
        with SessionLocal() as db:
            u = db.query(User).filter_by(email="dana@example.com").one()
            assert u.failed_login_count == 0
            assert u.locked_until is None
    finally:
        _cleanup("dana@example.com")
