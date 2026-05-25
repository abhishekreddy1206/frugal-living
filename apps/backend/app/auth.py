"""
Auth dependencies for FastAPI.

The two dependencies below are the single seam between the rest of the app and
the auth implementation. `CurrentUser` / `CurrentHousehold` keep their names
and types, so every existing router and service is untouched.

A valid session is required: the `hearth_session` cookie must hash to a row in
`core.sessions` that is not revoked and not expired. `get_current_household`
resolves to the session's `active_household_id`, falling back to (and persisting)
the user's first membership.

DEV_USER_ID / DEV_HOUSEHOLD_ID remain as constants — the test harness
(tests/conftest.py) seeds rows with these stable IDs and installs
`app.dependency_overrides` so every existing test acts as that fixture.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.db import get_db
from app.models.core import Household, HouseholdMember, User
from app.services.admin.bootstrap import bootstrap_admin
from app.services.auth.permissions import is_admin, is_at_least_moderator
from app.services.auth.sessions import get_session_by_raw_token
from app.services.flags.admin import seed_initial_flags
from app.services.ingredients import seed_starter_ingredients
from app.services.streaks import seed_badge_definitions

# Stable UUIDs for the test fixture user/household. They live here so the ~30
# test files that import `from app.auth import DEV_USER_ID, DEV_HOUSEHOLD_ID`
# keep working unchanged. The rows themselves are seeded by tests/conftest.py.
DEV_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEV_HOUSEHOLD_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
DEV_USER_EMAIL = "dev@frugal-living.local"


def seed_reference_data(db: DbSession) -> None:
    """Seed global, not-user-specific reference data on app startup.

    Replaces the old `seed_dev_fixtures` — the dev user/household auto-seed is
    gone; new users sign up through the UI. Also bootstraps the optional admin
    account from ADMIN_EMAIL/ADMIN_PASSWORD env vars (no-op when unset).
    """
    seed_starter_ingredients(db)
    seed_badge_definitions(db)
    seed_initial_flags(db)
    bootstrap_admin(
        db,
        email=settings.admin_email,
        password=settings.admin_password,
        display_name=settings.admin_display_name,
    )


def get_current_user(
    db: Annotated[DbSession, Depends(get_db)],
    session_token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> User:
    """Resolve the logged-in user from the session cookie. 401 if no valid session."""
    if not session_token:
        raise HTTPException(status_code=401, detail="not authenticated")
    sess = get_session_by_raw_token(db, session_token)
    if sess is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


def get_current_household(
    db: Annotated[DbSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    session_token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> Household:
    """Resolve the active household for the current session.

    Falls back to the user's first HouseholdMember and persists it on the
    session as the active household.
    """
    # Look up the session again (already validated by get_current_user).
    sess = get_session_by_raw_token(db, session_token) if session_token else None
    if sess is None:
        raise HTTPException(status_code=401, detail="not authenticated")

    if sess.active_household_id is not None:
        household = db.get(Household, sess.active_household_id)
        if household is not None:
            return household

    membership = (
        db.query(HouseholdMember)
        .filter(HouseholdMember.user_id == user.id)
        .order_by(HouseholdMember.created_at)
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=400, detail="user has no household")
    sess.active_household_id = membership.household_id
    db.flush()
    household = db.get(Household, membership.household_id)
    assert household is not None
    return household


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentHousehold = Annotated[Household, Depends(get_current_household)]


def require_admin(user: CurrentUser) -> User:
    """Raise 403 if the user is not an active admin."""
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="admin required")
    return user


def require_moderator(user: CurrentUser) -> User:
    """Pass if user is admin OR moderator. Used for moderation endpoints."""
    if not is_at_least_moderator(user):
        raise HTTPException(status_code=403, detail="moderator required")
    return user


CurrentAdmin = Annotated[User, Depends(require_admin)]
CurrentModerator = Annotated[User, Depends(require_moderator)]
