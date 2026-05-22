"""Tests for the chat schema models."""

from __future__ import annotations

from app.schemas.ai import ChatAction, ChatTurnResult


def test_chat_turn_result_parses_reply_and_actions():
    raw = {"reply": "Added rice.", "actions": [{"type": "add_pantry_item", "raw_name": "rice"}]}
    result = ChatTurnResult.model_validate(raw)
    assert result.reply == "Added rice."
    assert len(result.actions) == 1
    assert result.actions[0].type == "add_pantry_item"
    assert result.actions[0].raw_name == "rice"


def test_chat_turn_result_defaults_empty_actions():
    result = ChatTurnResult.model_validate({"reply": "hello"})
    assert result.actions == []


def test_chat_action_keeps_ids_as_raw_strings():
    """IDs stay strings so a malformed id degrades one action, not the whole turn."""
    action = ChatAction.model_validate(
        {"type": "remove_pantry_item", "pantry_item_id": "not-a-uuid"}
    )
    assert action.pantry_item_id == "not-a-uuid"


def test_chat_action_accepts_inventory_types_and_fields():
    from app.schemas.ai import ChatAction

    add = ChatAction(
        type="add_inventory_item",
        raw_name="DeWalt drill",
        category="tools",
        tags=["cordless"],
        condition="good",
        estimated_value_usd=90.0,
        location="garage",
    )
    assert add.type == "add_inventory_item"
    assert add.tags == ["cordless"]

    remove = ChatAction(
        type="remove_inventory_item",
        inventory_item_id="00000000-0000-0000-0000-000000000001",
    )
    assert remove.inventory_item_id is not None
