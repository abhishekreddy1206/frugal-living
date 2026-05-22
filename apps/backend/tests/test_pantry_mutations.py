"""Tests for the chat-facing pantry mutation helpers."""

from __future__ import annotations

import uuid

import pytest

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.core import Event, Household, User
from app.services.pantry import (
    PantryItemNotFound,
    add_item,
    soft_delete_item,
    update_item,
)


def _ctx(db):
    return db.get(Household, DEV_HOUSEHOLD_ID), db.get(User, DEV_USER_ID)


def test_add_item_resolves_ingredient_and_emits_event(db):
    household, user = _ctx(db)
    item = add_item(db, household=household, user=user, raw_name="rice", quantity=2, unit="lb")
    assert item.ingredient_id is not None  # "rice" is a starter ingredient
    assert item.source == "chat"
    events = (
        db.query(Event)
        .filter(Event.event_type == "food.pantry_item.added", Event.entity_id == item.id)
        .all()
    )
    assert len(events) == 1


def test_add_item_projects_expiry_from_shelf_life(db):
    household, user = _ctx(db)
    item = add_item(db, household=household, user=user, raw_name="rice")
    assert item.expires_at is not None  # rice has a 365-day shelf life


def test_soft_delete_item_sets_deleted_at_and_emits(db):
    household, user = _ctx(db)
    item = add_item(db, household=household, user=user, raw_name="quinoa")
    removed = soft_delete_item(db, household=household, user=user, pantry_item_id=item.id)
    assert removed.deleted_at is not None
    events = (
        db.query(Event)
        .filter(Event.event_type == "food.pantry_item.removed", Event.entity_id == item.id)
        .all()
    )
    assert len(events) == 1


def test_soft_delete_item_rejects_unknown_id(db):
    household, user = _ctx(db)
    with pytest.raises(PantryItemNotFound):
        soft_delete_item(db, household=household, user=user, pantry_item_id=uuid.uuid4())


def test_update_item_changes_fields_and_emits(db):
    household, user = _ctx(db)
    item = add_item(db, household=household, user=user, raw_name="eggs", quantity=6, unit="each")
    updated = update_item(db, household=household, user=user, pantry_item_id=item.id, quantity=12)
    assert float(updated.quantity) == 12.0
    events = (
        db.query(Event)
        .filter(Event.event_type == "food.pantry_item.updated", Event.entity_id == item.id)
        .all()
    )
    assert len(events) == 1


def test_update_item_no_op_emits_no_event(db):
    household, user = _ctx(db)
    item = add_item(db, household=household, user=user, raw_name="salt")
    update_item(db, household=household, user=user, pantry_item_id=item.id)
    events = (
        db.query(Event)
        .filter(Event.event_type == "food.pantry_item.updated", Event.entity_id == item.id)
        .all()
    )
    assert events == []


def test_update_item_rejects_unknown_id(db):
    household, user = _ctx(db)
    with pytest.raises(PantryItemNotFound):
        update_item(db, household=household, user=user, pantry_item_id=uuid.uuid4())
