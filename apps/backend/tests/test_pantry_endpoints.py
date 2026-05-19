"""End-to-end tests for the pantry capture + list endpoints."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.auth import DEV_HOUSEHOLD_ID
from app.db import SessionLocal
from app.main import app
from app.models.core import Event
from app.models.food import PantryItem
from app.services import llm


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_vision(monkeypatch):
    """Patch the Anthropic client used by extract_pantry_from_image."""
    fake = MagicMock()
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    return fake


def _vision_response(items: list[dict]) -> SimpleNamespace:
    import json
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps({"items": items}))]
    )


@pytest.fixture(autouse=True)
def _clean_pantry():
    """Wipe pantry rows and pantry events for the dev household before each test."""
    with SessionLocal() as db:
        db.query(PantryItem).filter(PantryItem.household_id == DEV_HOUSEHOLD_ID).delete()
        db.query(Event).filter(
            Event.household_id == DEV_HOUSEHOLD_ID,
            Event.event_type.like("food.pantry_item.%"),
        ).delete()
        db.commit()
    yield


def test_capture_creates_pantry_items_and_emits_events(client, mock_vision):
    mock_vision.messages.create.return_value = _vision_response(
        [
            {
                "raw_name": "Roma tomatoes",
                "quantity": 6,
                "unit": "each",
                "confidence": 0.9,
                "suggested_expires_at": None,
                "notes": None,
            },
            {
                "raw_name": "olive oil",
                "quantity": 1,
                "unit": "bottle",
                "confidence": 0.95,
                "suggested_expires_at": None,
                "notes": "looks half full",
            },
            {
                "raw_name": "dragonfruit",
                "quantity": 2,
                "unit": "each",
                "confidence": 0.6,
                "suggested_expires_at": None,
                "notes": None,
            },
        ]
    )

    resp = client.post(
        "/api/v1/food/pantry/capture",
        json={"image_base64": "x" * 64, "media_type": "image/jpeg"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created_count"] == 3
    assert {item["raw_name"] for item in body["items"]} == {
        "Roma tomatoes",
        "olive oil",
        "dragonfruit",
    }

    # Tomato resolves to a canonical id; dragonfruit does not.
    by_name = {i["raw_name"]: i for i in body["items"]}
    assert by_name["Roma tomatoes"]["ingredient_id"] is not None
    assert by_name["olive oil"]["ingredient_id"] is not None
    assert by_name["dragonfruit"]["ingredient_id"] is None

    # Tomato has shelf life — expires_at should be set even though LLM didn't suggest one.
    assert by_name["Roma tomatoes"]["expires_at"] is not None

    # Events: one per item, with the right type and entity refs.
    with SessionLocal() as db:
        events = (
            db.query(Event)
            .filter(
                Event.event_type == "food.pantry_item.added",
                Event.household_id == DEV_HOUSEHOLD_ID,
            )
            .all()
        )
        assert len(events) == 3
        assert all(e.entity_type == "pantry_item" for e in events)
        assert all(e.entity_id is not None for e in events)


def test_capture_with_empty_extraction_returns_zero(client, mock_vision):
    mock_vision.messages.create.return_value = _vision_response([])
    resp = client.post(
        "/api/v1/food/pantry/capture",
        json={"image_base64": "x" * 64},
    )
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "created_count": 0}


def test_capture_validates_image_field(client, mock_vision):
    """Missing image_base64 → 422; short string → 422 too (min_length=32)."""
    resp = client.post("/api/v1/food/pantry/capture", json={})
    assert resp.status_code == 422

    resp = client.post("/api/v1/food/pantry/capture", json={"image_base64": "short"})
    assert resp.status_code == 422


def test_list_pantry_returns_items_for_household(client, mock_vision):
    """After capture, GET /pantry returns the inserted rows."""
    mock_vision.messages.create.return_value = _vision_response(
        [
            {
                "raw_name": "rice",
                "quantity": 1,
                "unit": "lb",
                "confidence": 0.99,
                "suggested_expires_at": None,
                "notes": None,
            }
        ]
    )
    client.post("/api/v1/food/pantry/capture", json={"image_base64": "x" * 64})

    resp = client.get("/api/v1/food/pantry")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["raw_name"] == "rice"
    assert items[0]["source"] == "photo_capture"
