"""Tests for POST /auth/signup."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models.core import AuditLog, HouseholdMember, Subscription, User
from app.models.core import Session as AuthSession

pytestmark = pytest.mark.real_auth


@pytest.fixture
def client():
    return TestClient(app)


def test_signup_creates_user_household_membership_subscription_and_session(client):
    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "alice@example.com",
            "password": "hunter2hunter2",
            "display_name": "Alice",
            "household_name": "Alice's Place",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["email"] == "alice@example.com"
    assert body["household"]["name"] == "Alice's Place"
    # Cookie was set
    assert settings.session_cookie_name in resp.cookies

    with SessionLocal() as db:
        user = db.query(User).filter_by(email="alice@example.com").one()
        assert user.hashed_password is not None
        membership = db.query(HouseholdMember).filter_by(user_id=user.id).one()
        assert membership.role == "owner"
        sub = db.query(Subscription).filter_by(user_id=user.id).one()
        assert sub.tier_a_enabled is True
        assert sub.tier_b_enabled is True
        assert sub.tier_s_enabled is False
        household_id = membership.household_id
        # Delete in FK order: audit_log → session → membership/sub → household → user
        for al in db.query(AuditLog).filter_by(actor_user_id=user.id).all():
            db.delete(al)
        for sess in db.query(AuthSession).filter_by(user_id=user.id).all():
            db.delete(sess)
        db.flush()
        db.delete(membership)
        db.delete(sub)
        db.delete(db.query(__import__("app.models.core", fromlist=["Household"]).Household)
                  .filter_by(id=household_id).one())
        db.delete(user)
        db.commit()


def test_signup_rejects_short_password(client):
    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "bob@example.com", "password": "short",
            "display_name": "Bob", "household_name": "Bob",
        },
    )
    assert resp.status_code == 422


def test_signup_rejects_duplicate_email(client):
    first = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "carol@example.com", "password": "hunter2hunter2",
            "display_name": "Carol", "household_name": "Carol",
        },
    )
    assert first.status_code == 200
    dup = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "carol@example.com", "password": "different-password",
            "display_name": "Carol2", "household_name": "Carol2",
        },
    )
    assert dup.status_code == 409
    # Cleanup
    with SessionLocal() as db:
        u = db.query(User).filter_by(email="carol@example.com").one()
        membership = db.query(HouseholdMember).filter_by(user_id=u.id).one()
        sub = db.query(Subscription).filter_by(user_id=u.id).one()
        from app.models.core import Household as H
        household_id = membership.household_id
        h = db.get(H, household_id)
        # Delete in FK order: audit_log → session → membership/sub → household → user
        for al in db.query(AuditLog).filter_by(actor_user_id=u.id).all():
            db.delete(al)
        for sess in db.query(AuthSession).filter_by(user_id=u.id).all():
            db.delete(sess)
        db.flush()
        db.delete(sub)
        db.delete(membership)
        if h:
            db.delete(h)
        db.delete(u)
        db.commit()
