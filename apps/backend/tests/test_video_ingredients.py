"""Tests for the extract_video_ingredients LLM function."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import llm


def _fake_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def test_extract_video_ingredients_parses_recipe(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    fake.messages.create.return_value = _fake_response(
        json.dumps(
            {
                "is_recipe_video": True,
                "dish_name": "Tomato Pasta",
                "ingredients": ["tomato", "pasta", "garlic"],
            }
        )
    )
    result = llm.extract_video_ingredients("Easy Tomato Pasta", "A quick weeknight dinner.", ["pasta"])
    assert result.is_recipe_video is True
    assert result.dish_name == "Tomato Pasta"
    assert "garlic" in result.ingredients


def test_extract_video_ingredients_handles_non_recipe(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    fake.messages.create.return_value = _fake_response(
        '```json\n{"is_recipe_video": false, "dish_name": null, "ingredients": []}\n```'
    )
    result = llm.extract_video_ingredients("My budgeting tips", "How I save money.", [])
    assert result.is_recipe_video is False
    assert result.ingredients == []
