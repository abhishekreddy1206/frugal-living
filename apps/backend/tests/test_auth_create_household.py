"""Tests for POST /auth/households."""
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
        memberships = db.query(HouseholdMember).filter_by(user_id=u.id).all()
        for m in memberships:
            h = db.get(Household, m.household_id)
            db.delete(m)
            if h:
                db.delete(h)
        sub = db.query(Subscription).filter_by(user_id=u.id).one_or_none()
        if sub:
            db.delete(sub)
        db.delete(u)
        db.commit()


def test_create_household_makes_caller_owner():
    c = TestClient(app)
    c.post("/api/v1/auth/signup", json={
        "email": "hank@example.com", "password": "hunter2hunter2",
        "display_name": "Hank", "household_name": "Primary",
    })
    try:
        resp = c.post("/api/v1/auth/households", json={"name": "Vacation Home"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "Vacation Home"
        # Caller is owner; total memberships now 2
        with SessionLocal() as db:
            u = db.query(User).filter_by(email="hank@example.com").one()
            memberships = db.query(HouseholdMember).filter_by(user_id=u.id).all()
            assert len(memberships) == 2
            assert all(m.role == "owner" for m in memberships)
    finally:
        _cleanup("hank@example.com")
