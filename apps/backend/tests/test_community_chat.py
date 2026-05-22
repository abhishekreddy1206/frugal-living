"""Tests for inventory wiring in the chat orchestration service."""
from __future__ import annotations

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.community import CommunityItem
from app.models.core import Household, User
from app.schemas.ai import ChatAction
from app.services import chat
from app.services.community import items as items_service


def _ctx(db):
    return db.get(Household, DEV_HOUSEHOLD_ID), db.get(User, DEV_USER_ID)


def test_normalize_page_maps_inventory_route():
    assert chat.normalize_page("/inventory") == "inventory"


def test_inventory_conversation_has_community_scope(db):
    household, _ = _ctx(db)
    conv = chat.get_or_create_conversation(db, household=household, page="/inventory")
    assert conv.scope == "community"


def test_pantry_conversation_keeps_food_scope(db):
    household, _ = _ctx(db)
    conv = chat.get_or_create_conversation(db, household=household, page="/pantry")
    assert conv.scope == "food"


def test_build_page_context_lists_inventory_ids(db):
    household, user = _ctx(db)
    item = items_service.create_item(
        db, household=household, user=user, name="Catan", category="games"
    )
    context = chat.build_page_context(db, household=household, page="inventory")
    assert str(item.id) in context
    assert "Catan" in context


def test_execute_action_add_inventory_item_creates_row(db):
    household, user = _ctx(db)
    action = ChatAction(type="add_inventory_item", raw_name="Tent", category="outdoor")
    result = chat._execute_action(db, household=household, user=user, action=action)
    assert result.status == "ok"
    rows = db.query(CommunityItem).filter_by(household_id=household.id).all()
    assert any(r.name == "Tent" for r in rows)


def test_execute_action_remove_inventory_bad_id_returns_error(db):
    household, user = _ctx(db)
    action = ChatAction(type="remove_inventory_item", inventory_item_id="not-a-uuid")
    result = chat._execute_action(db, household=household, user=user, action=action)
    assert result.status == "error"
