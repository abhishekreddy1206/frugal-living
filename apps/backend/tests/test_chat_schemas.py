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
