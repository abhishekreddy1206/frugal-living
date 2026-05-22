"""
Shared pytest fixtures.

Tests run against the real local Postgres (per CLAUDE.md: do NOT use SQLite —
we rely on JSONB and array types). Each test runs inside a transaction that's
rolled back at teardown, so tests don't leak rows.

The starter ingredient catalog and dev household are seeded once at the start of
the session (idempotent) so resolver tests have a stable backdrop to query against.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.auth import DEV_HOUSEHOLD_ID, seed_dev_fixtures
from app.db import SessionLocal, engine
from app.models.ai import Briefing, Conversation
from app.models.content import ContentItem
from app.models.community import CommunityItem
from app.models.core import Event
from app.models.food import (
    FoodWasteEvent,
    MealPlan,
    PantryItem,
    PreservationJob,
    Recipe,
    ShoppingList,
)


@pytest.fixture(scope="session", autouse=True)
def _seed_session_fixtures():
    """Ensure dev household + ingredient catalog exist for all tests in this run."""
    seed_dev_fixtures()


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
