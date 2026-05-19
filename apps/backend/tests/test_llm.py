"""Tests for app.services.llm."""
from __future__ import annotations

import base64
import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.schemas.food import ExtractedPantry
from app.services import llm

# ---------- _extract_json ----------

def test_extract_json_bare():
    assert llm._extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    assert llm._extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_with_preamble():
    text = 'Here is your data:\n\n{"items": [{"raw_name": "rice"}]}\n\nHope that helps!'
    assert llm._extract_json(text) == {"items": [{"raw_name": "rice"}]}


def test_extract_json_raises_when_no_json():
    with pytest.raises(ValueError, match="could not extract JSON"):
        llm._extract_json("just text, no json at all")


# ---------- extract_pantry_from_image (mocked) ----------

def _mock_response(payload: dict) -> SimpleNamespace:
    text_block = SimpleNamespace(type="text", text=json.dumps(payload))
    return SimpleNamespace(content=[text_block])


@pytest.fixture
def mock_client(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(llm, "get_client", lambda: client)
    return client


def test_extract_pantry_from_image_happy_path(mock_client):
    mock_client.messages.create.return_value = _mock_response(
        {
            "items": [
                {
                    "raw_name": "Roma tomatoes",
                    "quantity": 6,
                    "unit": "each",
                    "confidence": 0.92,
                    "suggested_expires_at": None,
                    "notes": None,
                },
                {
                    "raw_name": "olive oil",
                    "quantity": 1,
                    "unit": "bottle",
                    "confidence": 0.98,
                    "suggested_expires_at": None,
                    "notes": "looks half full",
                },
            ]
        }
    )

    result = llm.extract_pantry_from_image("BASE64DATA" * 10)

    assert isinstance(result, ExtractedPantry)
    assert len(result.items) == 2
    assert result.items[0].raw_name == "Roma tomatoes"
    assert result.items[0].quantity == 6
    assert result.items[1].notes == "looks half full"

    # Verify request shape
    kwargs = mock_client.messages.create.call_args.kwargs
    assert kwargs["model"] == llm.MODEL_VISION
    assert "image" in str(kwargs["messages"])
    assert kwargs["messages"][0]["content"][0]["type"] == "image"
    assert kwargs["messages"][0]["content"][0]["source"]["media_type"] == "image/jpeg"


def test_extract_pantry_from_image_strips_fences(mock_client):
    text_block = SimpleNamespace(
        type="text",
        text='```json\n{"items": [{"raw_name": "rice", "confidence": 0.9}]}\n```',
    )
    mock_client.messages.create.return_value = SimpleNamespace(content=[text_block])

    result = llm.extract_pantry_from_image("BASE64DATA" * 10)
    assert len(result.items) == 1
    assert result.items[0].raw_name == "rice"


def test_extract_pantry_from_image_passes_media_type(mock_client):
    mock_client.messages.create.return_value = _mock_response({"items": []})
    llm.extract_pantry_from_image("BASE64DATA" * 10, media_type="image/png")
    kwargs = mock_client.messages.create.call_args.kwargs
    assert kwargs["messages"][0]["content"][0]["source"]["media_type"] == "image/png"


def test_extract_pantry_from_image_raises_on_empty_response(mock_client):
    mock_client.messages.create.return_value = SimpleNamespace(content=[])
    with pytest.raises(ValueError, match="no text content"):
        llm.extract_pantry_from_image("BASE64DATA" * 10)


# ---------- Live test (opt-in) ----------

@pytest.mark.skipif(
    os.getenv("LIVE_LLM") != "1",
    reason="Live LLM test only runs with LIVE_LLM=1",
)
def test_extract_pantry_from_image_live():
    """Hits the real Anthropic API. Burns tokens. Skip in CI by default."""
    # 1x1 transparent PNG
    tiny_png = base64.b64encode(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000d49444154789c63000100000005000100"
            "5d0d0a2d0000000049454e44ae426082"
        )
    ).decode()
    result = llm.extract_pantry_from_image(tiny_png, media_type="image/png")
    assert isinstance(result, ExtractedPantry)
