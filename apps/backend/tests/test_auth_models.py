"""Model-level tests for the auth tables."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.core import HouseholdInvite, Session


def test_session_roundtrip(db):
    s = Session(
        user_id=DEV_USER_ID,
        token_hash="a" * 64,
        active_household_id=DEV_HOUSEHOLD_ID,
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    db.add(s)
    db.flush()
    fetched = db.get(Session, s.id)
    assert fetched is not None
    assert fetched.token_hash == "a" * 64
    assert fetched.revoked_at is None
    assert fetched.metadata_ == {}


def test_household_invite_roundtrip(db):
    inv = HouseholdInvite(
        household_id=DEV_HOUSEHOLD_ID,
        token_hash="b" * 64,
        role="member",
        created_by_user_id=DEV_USER_ID,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(inv)
    db.flush()
    fetched = db.get(HouseholdInvite, inv.id)
    assert fetched is not None
    assert fetched.role == "member"
    assert fetched.accepted_at is None
    assert fetched.revoked_at is None
