"""Per-email login throttling. Updates failed_login_count / locked_until on User."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.models.core import User


def is_locked(user: User) -> tuple[bool, datetime | None]:
    """True if the user's account is currently in lockout."""
    if user.locked_until and user.locked_until > datetime.now(UTC):
        return True, user.locked_until
    return False, None


def register_failed_login(db: Session, user: User) -> None:
    """Increment the failure counter; engage lockout at the threshold."""
    user.failed_login_count += 1
    if user.failed_login_count >= settings.login_lockout_threshold:
        user.locked_until = datetime.now(UTC) + timedelta(
            minutes=settings.login_lockout_minutes
        )
    db.flush()


def reset_throttle(db: Session, user: User) -> None:
    """Clear failed-login state after a successful login."""
    user.failed_login_count = 0
    user.locked_until = None
    db.flush()
