"""Household-invite service — create, look up, accept, revoke."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session as DbSession

from app.models.core import HouseholdInvite, HouseholdMember, User
from app.services.auth.sessions import generate_session_token, hash_session_token

INVITE_TTL_DAYS = 7


def create_invite(
    db: DbSession,
    *,
    household_id,
    role: str,
    created_by_user_id,
    email: str | None = None,
) -> tuple[HouseholdInvite, str]:
    """Mint an invite; return (invite, raw_token)."""
    raw, hashed = generate_session_token()  # reuse the same hash scheme
    inv = HouseholdInvite(
        household_id=household_id,
        token_hash=hashed,
        role=role,
        created_by_user_id=created_by_user_id,
        email=email,
        expires_at=datetime.now(UTC) + timedelta(days=INVITE_TTL_DAYS),
    )
    db.add(inv)
    db.flush()
    return inv, raw


def get_invite_by_raw_token(db: DbSession, raw_token: str) -> HouseholdInvite | None:
    """Look up an invite by its raw token. Returns the row even if expired/accepted/revoked
    so callers can return the right 4xx; redeemability is checked by `is_redeemable`."""
    if not raw_token:
        return None
    return (
        db.query(HouseholdInvite)
        .filter(HouseholdInvite.token_hash == hash_session_token(raw_token))
        .one_or_none()
    )


def is_redeemable(inv: HouseholdInvite) -> bool:
    return (
        inv.accepted_at is None
        and inv.revoked_at is None
        and inv.expires_at > datetime.now(UTC)
    )


def revoke_invite(db: DbSession, inv: HouseholdInvite) -> None:
    if inv.revoked_at is None:
        inv.revoked_at = datetime.now(UTC)
        db.flush()


def accept_invite(db: DbSession, *, inv: HouseholdInvite, user: User) -> HouseholdMember:
    """Add the user as a HouseholdMember; mark the invite accepted."""
    existing = (
        db.query(HouseholdMember)
        .filter(
            HouseholdMember.user_id == user.id,
            HouseholdMember.household_id == inv.household_id,
        )
        .one_or_none()
    )
    if existing is None:
        membership = HouseholdMember(
            user_id=user.id, household_id=inv.household_id, role=inv.role,
        )
        db.add(membership)
    else:
        membership = existing
    inv.accepted_at = datetime.now(UTC)
    inv.accepted_by_user_id = user.id
    db.flush()
    return membership
