"""Session token generation, lookup, lifecycle, and cookie helpers.

Tokens: `secrets.token_urlsafe(32)` generates a 43-char URL-safe random string.
Only the SHA-256 hash is stored; the raw token lives in the cookie. A DB leak
therefore cannot yield live sessions.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Response
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.models.core import Session, User


def generate_session_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hash). The raw token goes in the cookie."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_session_token(raw)


def hash_session_token(raw: str) -> str:
    """SHA-256 hex digest of a raw session token."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_session(
    db: DbSession,
    *,
    user: User,
    active_household_id=None,
    user_agent: str | None = None,
    ip: str | None = None,
) -> tuple[Session, str]:
    """Create a session row; return (session, raw_token)."""
    raw, hashed = generate_session_token()
    now = datetime.now(UTC)
    meta: dict = {}
    if user_agent:
        meta["user_agent"] = user_agent
    if ip:
        meta["ip"] = ip
    sess = Session(
        user_id=user.id,
        token_hash=hashed,
        active_household_id=active_household_id,
        expires_at=now + timedelta(days=settings.session_max_age_days),
        last_used_at=now,
        metadata_=meta,
    )
    db.add(sess)
    db.flush()
    return sess, raw


def get_session_by_raw_token(db: DbSession, raw_token: str) -> Session | None:
    """Look up a valid session by its raw cookie token. Updates last_used_at on hit."""
    if not raw_token:
        return None
    hashed = hash_session_token(raw_token)
    sess = db.query(Session).filter(Session.token_hash == hashed).one_or_none()
    if sess is None:
        return None
    if sess.revoked_at is not None:
        return None
    if sess.expires_at <= datetime.now(UTC):
        return None
    sess.last_used_at = datetime.now(UTC)
    db.flush()
    return sess


def revoke_session(db: DbSession, sess: Session) -> None:
    """Mark a session revoked. Idempotent."""
    if sess.revoked_at is None:
        sess.revoked_at = datetime.now(UTC)
        db.flush()


def revoke_other_sessions(
    db: DbSession, *, user: User, except_session: Session | None = None
) -> int:
    """Revoke all of a user's non-revoked sessions except the given one. Returns count."""
    q = db.query(Session).filter(
        Session.user_id == user.id, Session.revoked_at.is_(None)
    )
    if except_session is not None:
        q = q.filter(Session.id != except_session.id)
    now = datetime.now(UTC)
    count = 0
    for s in q.all():
        s.revoked_at = now
        count += 1
    db.flush()
    return count


# ---------- Cookie helpers ----------


def set_session_cookie(response: Response, raw_token: str) -> None:
    """Attach the session cookie to a response."""
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        max_age=settings.session_max_age_days * 24 * 3600,
        httponly=True,
        samesite=settings.session_cookie_samesite,
        secure=settings.session_cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Remove the session cookie from the client."""
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
    )
