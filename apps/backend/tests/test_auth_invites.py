"""Tests for the household-invite endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models.core import (
    AuditLog,
    Household,
    HouseholdInvite,
    HouseholdMember,
    Subscription,
    User,
)
from app.models.core import (
    Session as DbSession,
)

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
        for inv in db.query(HouseholdInvite).filter_by(created_by_user_id=u.id).all():
            db.delete(inv)
        memberships = db.query(HouseholdMember).filter_by(user_id=u.id).all()
        for m in memberships:
            h = db.get(Household, m.household_id)
            db.delete(m)
            if h:
                for inv in db.query(HouseholdInvite).filter_by(household_id=h.id).all():
                    db.delete(inv)
                # Also remove any other members of this household
                for om in db.query(HouseholdMember).filter_by(household_id=h.id).all():
                    db.delete(om)
                db.delete(h)
        sub = db.query(Subscription).filter_by(user_id=u.id).one_or_none()
        if sub:
            db.delete(sub)
        db.delete(u)
        db.commit()


def _signup(email, household="HH"):
    c = TestClient(app)
    c.post("/api/v1/auth/signup", json={
        "email": email, "password": "hunter2hunter2",
        "display_name": email, "household_name": household,
    })
    return c


def test_owner_can_create_invite_and_invitee_can_accept():
    owner = _signup("karen@example.com", "Karen HQ")
    invitee = _signup("liam@example.com", "Liam HQ")
    try:
        with SessionLocal() as db:
            u = db.query(User).filter_by(email="karen@example.com").one()
            membership = db.query(HouseholdMember).filter_by(user_id=u.id).one()
            karen_hh = membership.household_id

        inv_resp = owner.post(
            f"/api/v1/auth/households/{karen_hh}/invites",
            json={"role": "member"},
        )
        assert inv_resp.status_code == 200, inv_resp.text
        token = inv_resp.json()["token"]

        preview = invitee.get(f"/api/v1/auth/invites/{token}")
        assert preview.status_code == 200
        assert preview.json()["household_name"] == "Karen HQ"
        assert preview.json()["role"] == "member"

        accept = invitee.post(f"/api/v1/auth/invites/{token}/accept")
        assert accept.status_code == 200

        with SessionLocal() as db:
            liam = db.query(User).filter_by(email="liam@example.com").one()
            mems = db.query(HouseholdMember).filter_by(user_id=liam.id).all()
            assert any(m.household_id == karen_hh and m.role == "member" for m in mems)
    finally:
        _cleanup("karen@example.com")
        _cleanup("liam@example.com")


def test_non_owner_cannot_create_invite():
    _owner = _signup("mike@example.com", "Mike HQ")
    other = _signup("nina@example.com", "Nina HQ")
    try:
        with SessionLocal() as db:
            mike = db.query(User).filter_by(email="mike@example.com").one()
            mike_hh = db.query(HouseholdMember).filter_by(user_id=mike.id).one().household_id

        resp = other.post(
            f"/api/v1/auth/households/{mike_hh}/invites",
            json={"role": "member"},
        )
        assert resp.status_code == 403
    finally:
        _cleanup("mike@example.com")
        _cleanup("nina@example.com")


def test_revoked_invite_cannot_be_accepted():
    owner = _signup("oscar@example.com", "Oscar HQ")
    invitee = _signup("pam@example.com", "Pam HQ")
    try:
        with SessionLocal() as db:
            o = db.query(User).filter_by(email="oscar@example.com").one()
            oscar_hh = db.query(HouseholdMember).filter_by(user_id=o.id).one().household_id
        created = owner.post(
            f"/api/v1/auth/households/{oscar_hh}/invites",
            json={"role": "member"},
        ).json()
        # Look up the invite id
        with SessionLocal() as db:
            inv = db.query(HouseholdInvite).filter_by(household_id=oscar_hh).order_by(
                HouseholdInvite.created_at.desc()
            ).first()
        rev = owner.delete(
            f"/api/v1/auth/households/{oscar_hh}/invites/{inv.id}"
        )
        assert rev.status_code == 200
        acc = invitee.post(f"/api/v1/auth/invites/{created['token']}/accept")
        assert acc.status_code == 410
    finally:
        _cleanup("oscar@example.com")
        _cleanup("pam@example.com")


def test_already_accepted_invite_returns_410():
    owner = _signup("quinn@example.com", "Quinn HQ")
    invitee = _signup("rose@example.com", "Rose HQ")
    try:
        with SessionLocal() as db:
            q = db.query(User).filter_by(email="quinn@example.com").one()
            q_hh = db.query(HouseholdMember).filter_by(user_id=q.id).one().household_id
        created = owner.post(
            f"/api/v1/auth/households/{q_hh}/invites", json={"role": "member"}
        ).json()
        first = invitee.post(f"/api/v1/auth/invites/{created['token']}/accept")
        assert first.status_code == 200
        second = invitee.post(f"/api/v1/auth/invites/{created['token']}/accept")
        assert second.status_code == 410
    finally:
        _cleanup("quinn@example.com")
        _cleanup("rose@example.com")
