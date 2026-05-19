"""Tests for app.services.events.emit_event."""
from __future__ import annotations

import uuid

import pytest

from app.models.core import Event, Household, User
from app.services.events import emit_event


def _make_user_and_household(db) -> tuple[User, Household]:
    user = User(email=f"test-{uuid.uuid4()}@example.com", display_name="Test")
    household = Household(name="Test Household")
    db.add_all([user, household])
    db.flush()
    return user, household


def test_emit_event_writes_row(db):
    user, household = _make_user_and_household(db)

    ev = emit_event(
        db,
        event_type="food.pantry_item.added",
        household_id=household.id,
        user_id=user.id,
        entity_type="pantry_item",
        entity_id=uuid.uuid4(),
        payload={"raw_name": "tomato", "quantity": 2.0},
    )

    assert ev.id is not None
    found = db.query(Event).filter_by(id=ev.id).one()
    assert found.event_type == "food.pantry_item.added"
    assert found.payload == {"raw_name": "tomato", "quantity": 2.0}
    assert found.household_id == household.id


def test_emit_event_defaults_payload_to_empty_dict(db):
    _user, household = _make_user_and_household(db)
    ev = emit_event(
        db,
        event_type="food.meal.cooked",
        household_id=household.id,
    )
    assert ev.payload == {}


@pytest.mark.parametrize(
    "bad_type",
    [
        "pantry_item_added",          # no dots
        "food.pantry_item",            # only one dot
        "Food.Pantry.Added",           # uppercase
        "food..added",                 # empty middle
        "food.pantry-item.added",      # hyphen
        "1food.pantry.added",          # leading digit
    ],
)
def test_emit_event_rejects_malformed_type(db, bad_type):
    with pytest.raises(ValueError, match="event_type"):
        emit_event(db, event_type=bad_type)


def test_emit_event_allows_null_household_and_user(db):
    """System-level events (e.g. nightly job) may not have a household or user."""
    ev = emit_event(db, event_type="core.system.tick")
    assert ev.household_id is None
    assert ev.user_id is None
