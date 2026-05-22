"""Tests for the chat orchestration service."""
from __future__ import annotations

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.core import Event, Household, User
from app.models.food import PantryItem
from app.schemas.ai import ChatAction, ChatTurnResult
from app.services import chat, llm
from app.services.pantry import add_item


def _ctx(db):
    return db.get(Household, DEV_HOUSEHOLD_ID), db.get(User, DEV_USER_ID)


def test_normalize_page_maps_routes_and_falls_back():
    assert chat.normalize_page("/pantry") == "pantry"
    assert chat.normalize_page("/") == "home"
    assert chat.normalize_page("pantry") == "pantry"
    assert chat.normalize_page("/something-new") == "general"


def test_get_or_create_conversation_is_idempotent_per_page(db):
    household, _ = _ctx(db)
    first = chat.get_or_create_conversation(db, household=household, page="/pantry")
    second = chat.get_or_create_conversation(db, household=household, page="/pantry")
    assert first.id == second.id


def test_get_or_create_conversation_distinct_per_page(db):
    household, _ = _ctx(db)
    pantry = chat.get_or_create_conversation(db, household=household, page="/pantry")
    plan = chat.get_or_create_conversation(db, household=household, page="/plan")
    assert pantry.id != plan.id


def test_build_page_context_includes_pantry_ids(db):
    household, user = _ctx(db)
    item = add_item(db, household=household, user=user, raw_name="rice")
    context = chat.build_page_context(db, household=household, page="pantry")
    assert str(item.id) in context


def test_execute_action_add_pantry_item_creates_row(db):
    household, user = _ctx(db)
    action = ChatAction(type="add_pantry_item", raw_name="lentils", quantity=3, unit="lb")
    result = chat._execute_action(db, household=household, user=user, action=action)
    assert result.status == "ok"
    rows = db.query(PantryItem).filter_by(household_id=household.id).all()
    assert any(r.raw_name == "lentils" for r in rows)


def test_execute_action_remove_with_bad_id_returns_error(db):
    household, user = _ctx(db)
    action = ChatAction(type="remove_pantry_item", pantry_item_id="not-a-uuid")
    result = chat._execute_action(db, household=household, user=user, action=action)
    assert result.status == "error"


def test_run_chat_turn_executes_actions_and_persists(db, monkeypatch):
    household, user = _ctx(db)
    conversation = chat.get_or_create_conversation(db, household=household, page="/pantry")
    monkeypatch.setattr(
        llm,
        "chat_turn",
        lambda history, context, page: ChatTurnResult(
            reply="Added coffee.",
            actions=[ChatAction(type="add_pantry_item", raw_name="coffee")],
        ),
    )
    response = chat.run_chat_turn(
        db, household=household, user=user, conversation=conversation, content="add coffee"
    )
    assert response.reply == "Added coffee."
    assert response.actions[0].status == "ok"
    rows = db.query(PantryItem).filter_by(household_id=household.id).all()
    assert any(r.raw_name == "coffee" for r in rows)
    events = db.query(Event).filter_by(event_type="food.pantry_item.added").all()
    assert len(events) == 1
