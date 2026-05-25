"""Pure-function role checks. No I/O, no DB. Reused by auth dependencies and routes."""
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
