"""Role-check helpers for auth dependencies and routes.

Pure-function predicates (is_admin, is_moderator, is_at_least_moderator):
    No I/O, no DB. Safe to call anywhere.

DB-backed guards (assert_not_last_admin):
    Require a live SQLAlchemy session. Raise HTTPException on violation.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session as DbSession

from app.models.core import User


def is_admin(u: User) -> bool:
    return u.role == "admin" and u.is_active


def is_moderator(u: User) -> bool:
    return u.role == "moderator" and u.is_active


def is_at_least_moderator(u: User) -> bool:
    return u.role in ("admin", "moderator") and u.is_active


def assert_not_last_admin(db: DbSession, target_user: User) -> None:
    """Block role-change-away-from-admin or deactivation of the last active admin."""
    if target_user.role != "admin":
        return
    # TODO(concurrency): consider SELECT FOR UPDATE before checking; two concurrent
    # demotions/deactivations could both pass this guard before either commits.
    other_admins = (
        db.query(User)
        .filter(
            User.id != target_user.id,
            User.role == "admin",
            User.is_active.is_(True),
        )
        .count()
    )
    if other_admins == 0:
        raise HTTPException(status_code=400, detail="cannot remove the last active admin")
