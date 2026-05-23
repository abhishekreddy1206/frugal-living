"""
Shared pytest fixtures.

Tests run against the real local Postgres (per CLAUDE.md: do NOT use SQLite —
we rely on JSONB and array types). Each test runs inside a transaction that's
rolled back at teardown, so tests don't leak rows.

Auth strategy: the dev user/household are seeded here (not at app startup) using
stable IDs from `app.auth` (DEV_USER_ID, DEV_HOUSEHOLD_ID). An autouse fixture
installs `app.dependency_overrides` for `get_current_user`/`get_current_household`
so every test resolves to the seeded fixture user/household, exactly as before.
Tests marked `@pytest.mark.real_auth` opt out of the override and exercise the
real signup/login/session flow.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.auth import (
    DEV_HOUSEHOLD_ID,
    DEV_USER_EMAIL,
    DEV_USER_ID,
    get_current_household,
    get_current_user,
    seed_reference_data,
)
from app.db import SessionLocal, engine
from app.main import app
from app.models.ai import Briefing, Conversation
from app.models.community import CommunityItem
from app.models.content import ContentItem
from app.models.core import (
    Event,
    Household,
    HouseholdMember,
    Subscription,
    User,
)
from app.models.food import (
    FoodWasteEvent,
    MealPlan,
    PantryItem,
    PreservationJob,
    Recipe,
    ShoppingList,
)


def _seed_test_user_and_household() -> None:
    """Seed the test User + Household + HouseholdMember + Subscription with stable IDs.

    This is the old `seed_dev_fixtures` logic, relocated from app startup. The
    IDs match the constants ~30 test files import from `app.auth`.
    """
    with SessionLocal() as db_:
        user = db_.get(User, DEV_USER_ID)
        if user is None:
            db_.add(User(id=DEV_USER_ID, email=DEV_USER_EMAIL, display_name="Test User"))
            db_.flush()

        household = db_.get(Household, DEV_HOUSEHOLD_ID)
        if household is None:
            db_.add(Household(id=DEV_HOUSEHOLD_ID, name="Test Household", size=2))
            db_.flush()

        membership = (
            db_.query(HouseholdMember)
            .filter_by(user_id=DEV_USER_ID, household_id=DEV_HOUSEHOLD_ID)
            .one_or_none()
        )
        if membership is None:
            db_.add(HouseholdMember(
                user_id=DEV_USER_ID, household_id=DEV_HOUSEHOLD_ID, role="owner"
            ))

        subscription = (
            db_.query(Subscription).filter_by(user_id=DEV_USER_ID).one_or_none()
        )
        if subscription is None:
            db_.add(Subscription(
                user_id=DEV_USER_ID, plan="suite", status="active",
                tier_a_enabled=True, tier_b_enabled=True,
            ))
        else:
            subscription.tier_b_enabled = True

        db_.commit()


@pytest.fixture(scope="session", autouse=True)
def _seed_session_fixtures():
    """Seed reference data (ingredients, badges) and the test user/household once per session."""
    _seed_test_user_and_household()
    with SessionLocal() as db_:
        seed_reference_data(db_)
        db_.commit()


def _override_get_current_user():
    with SessionLocal() as db_:
        return db_.get(User, DEV_USER_ID)


def _override_get_current_household():
    with SessionLocal() as db_:
        return db_.get(Household, DEV_HOUSEHOLD_ID)


@pytest.fixture(autouse=True)
def _auth_override(request):
    """Install dependency overrides for tests that act as the seeded fixture.

    Tests marked `@pytest.mark.real_auth` opt out — those tests exercise the
    real signup/login/session flow with no override.
    """
    if request.node.get_closest_marker("real_auth"):
        yield
        return
    app.dependency_overrides[get_current_user] = _override_get_current_user
    app.dependency_overrides[get_current_household] = _override_get_current_household
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_household, None)


@pytest.fixture(autouse=True)
def _clean_household_data():
    """Wipe per-household state before each test so endpoint tests (which commit)
    don't bleed into subsequent tests. The dev household + ingredient catalog
    are preserved."""
    with SessionLocal() as db_:
        # Order matters for FKs: child tables before parents.
        db_.query(FoodWasteEvent).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        db_.query(PreservationJob).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        db_.query(ShoppingList).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        db_.query(MealPlan).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        db_.query(PantryItem).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        db_.query(CommunityItem).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        # Recipes are not scoped by household, but we wipe ai-generated ones
        # because tests create them freely. User-created recipes (if any) stay.
        db_.query(Recipe).filter_by(is_ai_generated=True).delete()
        db_.query(Briefing).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        # Content items are global (no household_id); tests create them freely.
        db_.query(ContentItem).delete()
        db_.query(Conversation).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        # Events are wiped wholesale: some (e.g. content enrichment) have no
        # household_id, and no test depends on pre-existing event rows.
        db_.query(Event).delete()
        db_.commit()
    yield


@pytest.fixture
def db() -> Session:
    """A SQLAlchemy session bound to a transaction that rolls back at teardown."""
    connection = engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
