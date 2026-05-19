"""
Dev-mode auth stub. Per CLAUDE.md: real auth (Clerk/Auth.js) plugs in pre-launch.

For now: a single fixture User + Household + HouseholdMember + Subscription
is seeded on app startup (idempotent). FastAPI dependencies resolve every
request to that household. Real auth replaces these two dependencies and the
seed call goes away.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.models.core import Household, HouseholdMember, Subscription, User
from app.services.ingredients import seed_starter_ingredients

# Stable UUIDs so the dev household is the same across restarts and migrations.
DEV_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEV_HOUSEHOLD_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")

DEV_USER_EMAIL = "dev@frugal-living.local"


def seed_dev_fixtures() -> None:
    """Idempotent: create the dev user/household/membership/subscription if absent."""
    with SessionLocal() as db:
        user = db.get(User, DEV_USER_ID)
        if user is None:
            user = User(
                id=DEV_USER_ID,
                email=DEV_USER_EMAIL,
                display_name="Dev User",
            )
            db.add(user)
            db.flush()

        household = db.get(Household, DEV_HOUSEHOLD_ID)
        if household is None:
            household = Household(
                id=DEV_HOUSEHOLD_ID,
                name="Dev Household",
                size=2,
            )
            db.add(household)
            db.flush()

        membership = (
            db.query(HouseholdMember)
            .filter_by(user_id=DEV_USER_ID, household_id=DEV_HOUSEHOLD_ID)
            .one_or_none()
        )
        if membership is None:
            db.add(
                HouseholdMember(
                    user_id=DEV_USER_ID,
                    household_id=DEV_HOUSEHOLD_ID,
                    role="owner",
                )
            )

        subscription = (
            db.query(Subscription).filter_by(user_id=DEV_USER_ID).one_or_none()
        )
        if subscription is None:
            db.add(
                Subscription(
                    user_id=DEV_USER_ID,
                    plan="suite",
                    status="active",
                    tier_a_enabled=True,
                )
            )

        db.commit()

        seed_starter_ingredients(db)


def get_current_user(db: Annotated[Session, Depends(get_db)]) -> User:
    user = db.get(User, DEV_USER_ID)
    if user is None:
        raise RuntimeError(
            "Dev user not seeded. Ensure seed_dev_fixtures() runs on startup."
        )
    return user


def get_current_household(
    db: Annotated[Session, Depends(get_db)],
) -> Household:
    household = db.get(Household, DEV_HOUSEHOLD_ID)
    if household is None:
        raise RuntimeError(
            "Dev household not seeded. Ensure seed_dev_fixtures() runs on startup."
        )
    return household


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentHousehold = Annotated[Household, Depends(get_current_household)]
