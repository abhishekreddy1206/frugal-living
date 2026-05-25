"""Idempotent admin bootstrap from env vars. Runs at app startup."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session as DbSession

from app.models.core import AuditLog, Household, HouseholdMember, User
from app.services.auth.passwords import hash_password

logger = logging.getLogger(__name__)


def bootstrap_admin(
    db: DbSession,
    *,
    email: str | None,
    password: str | None,
    display_name: str | None,
) -> None:
    """Idempotent: create the bootstrap admin if missing; ensure role=admin if present.

    NEVER overwrites an existing password. Rotate via POST /auth/password.
    No-op when email is falsy (production hardening: explicit opt-in only).
    """
    if not email:
        return
    if not password:
        logger.warning("ADMIN_EMAIL set without ADMIN_PASSWORD; bootstrap skipped")
        return

    existing = db.query(User).filter_by(email=email).one_or_none()
    if existing is None:
        name = display_name or email.split("@")[0]
        user = User(
            email=email,
            hashed_password=hash_password(password),
            display_name=name,
            role="admin",
            is_active=True,
            email_verified=True,
        )
        db.add(user)
        db.flush()
        household = Household(name=f"{name}'s Household", size=1)
        db.add(household)
        db.flush()
        db.add(HouseholdMember(user_id=user.id, household_id=household.id, role="owner"))
        db.add(AuditLog(
            actor_user_id=user.id,
            action="admin.bootstrap.created",
            target_type="user",
            target_id=user.id,
            payload={"email": email},
        ))
        logger.info("bootstrap admin created: %s", email)
        return

    # User exists; ensure admin role + active. Never touch the password.
    if existing.role != "admin" or not existing.is_active:
        existing.role = "admin"
        existing.is_active = True
        db.add(AuditLog(
            actor_user_id=existing.id,
            action="admin.bootstrap.promoted",
            target_type="user",
            target_id=existing.id,
            payload={"email": email},
        ))
        logger.info("bootstrap admin promoted: %s", email)
