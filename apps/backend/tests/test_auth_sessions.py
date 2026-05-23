"""Tests for session token generation and lifecycle."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.core import User
from app.services.auth import sessions as session_svc


def test_generate_token_returns_raw_and_hash():
    raw, hashed = session_svc.generate_session_token()
    assert raw and hashed
    assert raw != hashed
    assert len(hashed) == 64  # sha256 hex
    assert session_svc.hash_session_token(raw) == hashed


def test_create_and_lookup_session(db):
    user = db.get(User, DEV_USER_ID)
    sess, raw = session_svc.create_session(
        db, user=user, active_household_id=DEV_HOUSEHOLD_ID,
        user_agent="pytest", ip="127.0.0.1",
    )
    assert sess.id is not None
    assert sess.token_hash == session_svc.hash_session_token(raw)
    assert sess.expires_at > datetime.now(UTC)
    assert sess.revoked_at is None
    assert sess.metadata_ == {"user_agent": "pytest", "ip": "127.0.0.1"}

    fetched = session_svc.get_session_by_raw_token(db, raw)
    assert fetched is not None
    assert fetched.id == sess.id
    assert fetched.last_used_at is not None


def test_revoked_session_is_not_returned(db):
    user = db.get(User, DEV_USER_ID)
    sess, raw = session_svc.create_session(
        db, user=user, active_household_id=DEV_HOUSEHOLD_ID,
    )
    session_svc.revoke_session(db, sess)
    assert session_svc.get_session_by_raw_token(db, raw) is None


def test_expired_session_is_not_returned(db):
    user = db.get(User, DEV_USER_ID)
    sess, raw = session_svc.create_session(
        db, user=user, active_household_id=DEV_HOUSEHOLD_ID,
    )
    sess.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.flush()
    assert session_svc.get_session_by_raw_token(db, raw) is None


def test_unknown_token_returns_none(db):
    assert session_svc.get_session_by_raw_token(db, "no-such-token") is None


def test_revoke_other_sessions(db):
    user = db.get(User, DEV_USER_ID)
    s1, _ = session_svc.create_session(db, user=user, active_household_id=DEV_HOUSEHOLD_ID)
    s2, _ = session_svc.create_session(db, user=user, active_household_id=DEV_HOUSEHOLD_ID)
    s3, _ = session_svc.create_session(db, user=user, active_household_id=DEV_HOUSEHOLD_ID)
    session_svc.revoke_other_sessions(db, user=user, except_session=s2)
    db.refresh(s1)
    db.refresh(s2)
    db.refresh(s3)
    assert s1.revoked_at is not None
    assert s2.revoked_at is None
    assert s3.revoked_at is not None
