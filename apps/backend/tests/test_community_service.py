"""Tests for the community inventory service layer."""
from __future__ import annotations

import uuid

import pytest

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.core import Event, Household, User
from app.services.community import items as items_service
from app.services.community.items import CommunityItemNotFound


def _ctx(db):
    return db.get(Household, DEV_HOUSEHOLD_ID), db.get(User, DEV_USER_ID)


def test_create_item_persists_and_emits_event(db):
    household, user = _ctx(db)
    item = items_service.create_item(
        db, household=household, user=user, name="Catan", category="games"
    )
    assert item.id is not None
    events = db.query(Event).filter_by(event_type="community.item.added").all()
    assert len(events) == 1
    assert events[0].entity_type == "item"
    assert events[0].entity_id == item.id


def test_create_item_coerces_unknown_category_to_other(db):
    household, user = _ctx(db)
    item = items_service.create_item(
        db, household=household, user=user, name="Mystery", category="spaceship"
    )
    assert item.category == "other"


def test_list_items_filters_by_category(db):
    household, user = _ctx(db)
    items_service.create_item(db, household=household, user=user, name="Drill", category="tools")
    items_service.create_item(db, household=household, user=user, name="Catan", category="games")
    tools = items_service.list_items(db, household=household, category="tools")
    assert [i.name for i in tools] == ["Drill"]


def test_update_item_changes_fields_and_emits_event(db):
    household, user = _ctx(db)
    item = items_service.create_item(db, household=household, user=user, name="Drill")
    items_service.update_item(
        db, household=household, user=user, item_id=item.id, location="garage"
    )
    assert item.location == "garage"
    events = db.query(Event).filter_by(event_type="community.item.updated").all()
    assert len(events) == 1


def test_soft_delete_item_sets_deleted_at_and_emits_event(db):
    household, user = _ctx(db)
    item = items_service.create_item(db, household=household, user=user, name="Drill")
    items_service.soft_delete_item(db, household=household, user=user, item_id=item.id)
    assert item.deleted_at is not None
    assert items_service.list_items(db, household=household) == []
    events = db.query(Event).filter_by(event_type="community.item.removed").all()
    assert len(events) == 1


def test_load_unknown_item_raises(db):
    household, user = _ctx(db)
    with pytest.raises(CommunityItemNotFound):
        items_service.update_item(
            db, household=household, user=user, item_id=uuid.uuid4(), name="x"
        )
