"""Bootstrap is idempotent, never overwrites passwords, promotes existing users."""
from __future__ import annotations

import uuid

import pytest

from app.db import SessionLocal
from app.models.core import AuditLog, Household, HouseholdMember, Subscription, User
from app.services.admin.bootstrap import bootstrap_admin


@pytest.fixture
def fresh_email() -> str:
    return f"admin-{uuid.uuid4().hex[:8]}@test.local"


def test_bootstrap_noop_when_email_unset(fresh_email):
    # Use SessionLocal like the other tests so the fixture contract is consistent —
    # if bootstrap ever starts committing, the rollback-based `db` fixture would
    # hide regressions while the SessionLocal-based tests would catch them.
    with SessionLocal() as db_:
        before = db_.query(User).count()
        bootstrap_admin(db_, email=None, password="x", display_name=None)
        assert db_.query(User).count() == before


def test_bootstrap_creates_user_when_missing(fresh_email):
    with SessionLocal() as db_:
        bootstrap_admin(db_, email=fresh_email, password="bootstrap-pw", display_name="Boss")
        db_.commit()
    with SessionLocal() as db_:
        u = db_.query(User).filter_by(email=fresh_email).one()
        assert u.role == "admin"
        assert u.is_active is True
        assert u.email_verified is True
        assert u.hashed_password is not None
        # Has a personal household with owner membership
        membership = db_.query(HouseholdMember).filter_by(user_id=u.id).one()
        assert membership.role == "owner"
        hh = db_.get(Household, membership.household_id)
        assert hh.name == "Boss's Household"
        # Subscription mirrors the signup flow (every User gets one)
        sub = db_.query(Subscription).filter_by(user_id=u.id).one()
        assert sub.plan == "suite"
        assert sub.tier_a_enabled is True
        assert sub.tier_b_enabled is True
        assert sub.tier_s_enabled is True
        # Audit row written
        audit = db_.query(AuditLog).filter_by(action="admin.bootstrap.created").all()
        assert any(a.payload.get("email") == fresh_email for a in audit)


def test_bootstrap_promotes_existing_non_admin(fresh_email):
    # Pre-create a regular user
    with SessionLocal() as db_:
        u = User(email=fresh_email, hashed_password="$2b$12$abcdefg", role="user")
        db_.add(u)
        db_.commit()

    with SessionLocal() as db_:
        bootstrap_admin(db_, email=fresh_email, password="ignored", display_name="X")
        db_.commit()

    with SessionLocal() as db_:
        u = db_.query(User).filter_by(email=fresh_email).one()
        assert u.role == "admin"
        # Password untouched
        assert u.hashed_password == "$2b$12$abcdefg"
        audit = db_.query(AuditLog).filter_by(action="admin.bootstrap.promoted").all()
        assert any(a.payload.get("email") == fresh_email for a in audit)


def test_bootstrap_idempotent_on_existing_admin(fresh_email):
    with SessionLocal() as db_:
        bootstrap_admin(db_, email=fresh_email, password="pw", display_name="Z")
        db_.commit()
    # Second run should not duplicate audit rows
    with SessionLocal() as db_:
        before = db_.query(AuditLog).filter_by(action="admin.bootstrap.created").count()
        bootstrap_admin(db_, email=fresh_email, password="pw", display_name="Z")
        db_.commit()
        after = db_.query(AuditLog).filter_by(action="admin.bootstrap.created").count()
        assert after == before
