"""Tests for the dev auth fixture + dependencies.

The dev user/household are no longer seeded by `seed_dev_fixtures` at app
startup — that function is gone. Instead, `tests/conftest.py` seeds the fixture
rows using the stable IDs from `app.auth` and installs `app.dependency_overrides`
so every test resolves to that fixture user/household. These tests verify the
seeded rows exist as expected (they rely on the session-scoped `_seed_session_fixtures`
autouse fixture in conftest.py).
"""
from __future__ import annotations

from app.auth import (
    DEV_HOUSEHOLD_ID,
    DEV_USER_EMAIL,
    DEV_USER_ID,
)
from app.db import SessionLocal
from app.models.core import Household, HouseholdMember, Subscription, User


def test_dev_user_and_household_are_seeded():
    """The conftest seeds the dev user/household; verify rows exist."""
    with SessionLocal() as db:
        user = db.get(User, DEV_USER_ID)
        household = db.get(Household, DEV_HOUSEHOLD_ID)
        assert user is not None
        assert user.email == DEV_USER_EMAIL
        assert household is not None

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


def test_dev_subscription_has_tier_b_enabled():
    with SessionLocal() as db:
        sub = db.query(Subscription).filter_by(user_id=DEV_USER_ID).one()
        assert sub.tier_b_enabled is True
