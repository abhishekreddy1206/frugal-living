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

import uuid as _uuid_for_fixture

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
from app.models.community import (
    Community,
    CommunityItem,
    CommunityJoinRequest,
    CommunityMember,
    Listing,
    ListingCommunity,
)
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

# Stable IDs for the second fixture household used in cross-household visibility tests.
SECOND_USER_ID = _uuid_for_fixture.UUID("00000000-0000-0000-0000-000000000011")
SECOND_HOUSEHOLD_ID = _uuid_for_fixture.UUID("00000000-0000-0000-0000-000000000012")
SECOND_USER_EMAIL = "second@frugal-living.local"


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

        second_user = db_.get(User, SECOND_USER_ID)
        if second_user is None:
            db_.add(User(id=SECOND_USER_ID, email=SECOND_USER_EMAIL, display_name="Second User"))
            db_.flush()

        second_household = db_.get(Household, SECOND_HOUSEHOLD_ID)
        if second_household is None:
            db_.add(Household(id=SECOND_HOUSEHOLD_ID, name="Second Household", size=1))
            db_.flush()

        if (
            db_.query(HouseholdMember)
            .filter_by(user_id=SECOND_USER_ID, household_id=SECOND_HOUSEHOLD_ID)
            .one_or_none() is None
        ):
            db_.add(HouseholdMember(
                user_id=SECOND_USER_ID, household_id=SECOND_HOUSEHOLD_ID, role="owner",
            ))

        if db_.query(Subscription).filter_by(user_id=SECOND_USER_ID).one_or_none() is None:
            db_.add(Subscription(
                user_id=SECOND_USER_ID, plan="free", status="active",
                tier_a_enabled=True, tier_b_enabled=True,
            ))

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
        # Reset location metadata for both households so radius tests start clean.
        for hid in (DEV_HOUSEHOLD_ID, SECOND_HOUSEHOLD_ID):
            h = db_.get(Household, hid)
            if h is not None:
                md = dict(h.metadata_ or {})
                md.pop("lat", None)
                md.pop("lng", None)
                md.pop("share_radius_miles", None)
                h.metadata_ = md

        # Order matters for FKs: child tables before parents.
        db_.query(FoodWasteEvent).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        db_.query(PreservationJob).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        db_.query(ShoppingList).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        db_.query(MealPlan).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        db_.query(PantryItem).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        # Phase 2: listing_communities -> listings -> (then items below)
        db_.query(ListingCommunity).delete()
        db_.query(Listing).delete()
        # Phase 2: community memberships + join requests + communities
        db_.query(CommunityMember).delete()
        db_.query(CommunityJoinRequest).delete()
        db_.query(Community).delete()
        db_.query(CommunityItem).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        db_.query(CommunityItem).filter_by(household_id=SECOND_HOUSEHOLD_ID).delete()
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


@pytest.fixture
def second_household(db) -> Household:
    """The second seeded household (separate from the default DEV_HOUSEHOLD_ID).
    For tests that need two households to exercise cross-household visibility."""
    h = db.get(Household, SECOND_HOUSEHOLD_ID)
    assert h is not None
    return h


@pytest.fixture
def second_user(db) -> User:
    u = db.get(User, SECOND_USER_ID)
    assert u is not None
    return u


def set_household_location(db, household: Household, lat: float, lng: float) -> None:
    """Test helper — write lat/lng into the household's metadata_ JSONB."""
    md = dict(household.metadata_ or {})
    md["lat"] = lat
    md["lng"] = lng
    household.metadata_ = md
    db.flush()
