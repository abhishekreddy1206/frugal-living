"""Tests for the dev auth fixture + dependencies."""
from __future__ import annotations

from app.auth import (
    DEV_HOUSEHOLD_ID,
    DEV_USER_ID,
    seed_dev_fixtures,
)
from app.db import SessionLocal
from app.models.core import Household, HouseholdMember, Subscription, User


def test_seed_dev_fixtures_creates_and_is_idempotent():
    """Calling seed twice should not duplicate rows."""
    seed_dev_fixtures()
    seed_dev_fixtures()

    with SessionLocal() as db:
        user = db.get(User, DEV_USER_ID)
        household = db.get(Household, DEV_HOUSEHOLD_ID)
        assert user is not None
        assert user.email == "dev@frugal-living.local"
        assert household is not None
        assert household.name == "Dev Household"

        memberships = (
            db.query(HouseholdMember)
            .filter_by(user_id=DEV_USER_ID, household_id=DEV_HOUSEHOLD_ID)
            .all()
        )
        assert len(memberships) == 1
        assert memberships[0].role == "owner"

        subs = db.query(Subscription).filter_by(user_id=DEV_USER_ID).all()
        assert len(subs) == 1
        assert subs[0].tier_a_enabled is True
