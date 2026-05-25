"""Pure-function role checks. No I/O, no DB. Reused by auth dependencies and routes."""
from __future__ import annotations

from app.models.core import User


def is_admin(u: User) -> bool:
    return u.role == "admin" and u.is_active


def is_moderator(u: User) -> bool:
    return u.role == "moderator" and u.is_active


def is_at_least_moderator(u: User) -> bool:
    return u.role in ("admin", "moderator") and u.is_active
