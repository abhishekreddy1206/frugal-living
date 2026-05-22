"""Tests for the inventory vision-extraction LLM function."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import llm


def _vision_response(items: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps({"items": items}))]
    )


def test_extract_items_from_image_parses_response(monkeypatch):
    fake = MagicMock()
    fake.messages.create.return_value = _vision_response(
        [
            {
                "name": "DeWalt 20V drill",
                "category": "tools",
                "tags": ["cordless", "power tool"],
                "quantity": 1,
                "condition": "good",
                "estimated_value_usd": 90,
                "confidence": 0.92,
                "notes": None,
            },
            {
                "name": "Catan",
                "category": "games",
                "tags": ["board game"],
                "quantity": 1,
                "condition": None,
                "estimated_value_usd": 35,
                "confidence": 0.97,
                "notes": None,
            },
        ]
    )
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    result = llm.extract_items_from_image("x" * 64, "image/jpeg")

    assert len(result.items) == 2
    assert result.items[0].name == "DeWalt 20V drill"
    assert result.items[0].category == "tools"
    assert result.items[1].name == "Catan"
