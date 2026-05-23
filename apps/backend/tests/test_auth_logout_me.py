"""Tests for POST /auth/logout and GET /auth/me."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
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


def _signup_and_client():
    c = TestClient(app)
    c.post(
        "/api/v1/auth/signup",
        json={
            "email": "ed@example.com",
            "password": "hunter2hunter2",
            "display_name": "Ed",
            "household_name": "Ed",
        },
    )
    return c


def test_me_returns_user_memberships_and_active_household():
    c = _signup_and_client()
    try:
        resp = c.get("/api/v1/auth/me")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["user"]["email"] == "ed@example.com"
        assert len(body["memberships"]) == 1
        assert body["memberships"][0]["role"] == "owner"
        assert body["active_household"]["name"] == "Ed"
    finally:
        _cleanup("ed@example.com")


def test_me_without_cookie_returns_401():
    c = TestClient(app)
    resp = c.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_logout_revokes_session_and_clears_cookie():
    c = _signup_and_client()
    try:
        with SessionLocal() as db:
            u = db.query(User).filter_by(email="ed@example.com").one()
            assert db.query(DbSession).filter_by(user_id=u.id, revoked_at=None).count() == 1

        resp = c.post("/api/v1/auth/logout")
        assert resp.status_code == 200
        # Cookie deleted (Set-Cookie with Max-Age=0 / expires in the past)
        cookie_header = resp.headers.get("set-cookie", "")
        assert settings.session_cookie_name in cookie_header

        with SessionLocal() as db:
            u = db.query(User).filter_by(email="ed@example.com").one()
            assert db.query(DbSession).filter_by(user_id=u.id, revoked_at=None).count() == 0

        # The same client can no longer access /me.
        me = c.get("/api/v1/auth/me")
        assert me.status_code == 401
    finally:
        _cleanup("ed@example.com")
