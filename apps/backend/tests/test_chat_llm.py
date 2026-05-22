"""Tests for the chat_turn LLM function."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import llm


def test_chat_turn_parses_reply_and_actions(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    fake.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text",
                text=json.dumps(
                    {
                        "reply": "Added rice to your pantry.",
                        "actions": [{"type": "add_pantry_item", "raw_name": "rice"}],
                    }
                ),
            )
        ]
    )
    result = llm.chat_turn([{"role": "user", "content": "add rice"}], "PANTRY: (empty)", "pantry")
    assert result.reply == "Added rice to your pantry."
    assert result.actions[0].type == "add_pantry_item"
    assert result.actions[0].raw_name == "rice"


def test_chat_turn_handles_fenced_json(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    fake.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text",
                text='```json\n{"reply": "Hi there.", "actions": []}\n```',
            )
        ]
    )
    result = llm.chat_turn([{"role": "user", "content": "hi"}], "", "home")
    assert result.reply == "Hi there."
    assert result.actions == []


def test_chat_turn_raises_on_empty_response(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    fake.messages.create.return_value = SimpleNamespace(content=[])
    with pytest.raises(ValueError, match="no text content"):
        llm.chat_turn([{"role": "user", "content": "hi"}], "", "home")
