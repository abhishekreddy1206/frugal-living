"""Tests for POST /auth/switch-household."""

from __future__ import annotations

import uuid

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


def test_switch_to_a_household_you_belong_to():
    c = TestClient(app)
    c.post(
        "/api/v1/auth/signup",
        json={
            "email": "ivy@example.com",
            "password": "hunter2hunter2",
            "display_name": "Ivy",
            "household_name": "Primary",
        },
    )
    try:
        new = c.post("/api/v1/auth/households", json={"name": "Cabin"}).json()
        resp = c.post("/api/v1/auth/switch-household", json={"household_id": new["id"]})
        assert resp.status_code == 200, resp.text
        me = c.get("/api/v1/auth/me").json()
        assert me["active_household"]["id"] == new["id"]
    finally:
        _cleanup("ivy@example.com")


def test_switch_to_unknown_household_returns_403():
    c = TestClient(app)
    c.post(
        "/api/v1/auth/signup",
        json={
            "email": "jack@example.com",
            "password": "hunter2hunter2",
            "display_name": "Jack",
            "household_name": "Primary",
        },
    )
    try:
        resp = c.post("/api/v1/auth/switch-household", json={"household_id": str(uuid.uuid4())})
        assert resp.status_code == 403
    finally:
        _cleanup("jack@example.com")
