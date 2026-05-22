"""End-to-end tests for the community inventory endpoints."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.auth import DEV_HOUSEHOLD_ID
from app.db import SessionLocal
from app.main import app
from app.models.core import Event
from app.services import llm


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_vision(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    return fake


def _vision_response(items: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps({"items": items}))]
    )


def test_create_and_list_item(client):
    resp = client.post(
        "/api/v1/community/items",
        json={"name": "Catan", "category": "games"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Catan"

    listed = client.get("/api/v1/community/items")
    assert listed.status_code == 200
    assert [i["name"] for i in listed.json()] == ["Catan"]


def test_list_filters_by_category(client):
    client.post("/api/v1/community/items", json={"name": "Drill", "category": "tools"})
    client.post("/api/v1/community/items", json={"name": "Catan", "category": "games"})
    resp = client.get("/api/v1/community/items?category=tools")
    assert [i["name"] for i in resp.json()] == ["Drill"]


def test_create_rejects_unknown_category(client):
    resp = client.post(
        "/api/v1/community/items", json={"name": "x", "category": "vehicles"}
    )
    assert resp.status_code == 422


def test_capture_creates_items_and_emits_events(client, mock_vision):
    mock_vision.messages.create.return_value = _vision_response(
        [
            {
                "name": "DeWalt drill",
                "category": "tools",
                "tags": ["cordless"],
                "quantity": 1,
                "condition": "good",
                "estimated_value_usd": 90,
                "confidence": 0.9,
                "notes": None,
            },
            {
                "name": "Catan",
                "category": "games",
                "tags": ["board game"],
                "quantity": 1,
                "condition": None,
                "estimated_value_usd": 35,
                "confidence": 0.95,
                "notes": None,
            },
        ]
    )
    resp = client.post(
        "/api/v1/community/items/capture",
        json={"image_base64": "x" * 64, "media_type": "image/jpeg"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created_count"] == 2

    with SessionLocal() as db:
        events = (
            db.query(Event)
            .filter(
                Event.event_type == "community.item.added",
                Event.household_id == DEV_HOUSEHOLD_ID,
            )
            .all()
        )
        assert len(events) == 2
        assert all(e.entity_type == "item" for e in events)


def test_update_item(client):
    created = client.post(
        "/api/v1/community/items", json={"name": "Drill", "category": "tools"}
    ).json()
    resp = client.patch(
        f"/api/v1/community/items/{created['id']}", json={"location": "garage"}
    )
    assert resp.status_code == 200
    assert resp.json()["location"] == "garage"


def test_update_unknown_item_returns_404(client):
    resp = client.patch(
        "/api/v1/community/items/00000000-0000-0000-0000-0000000000ff",
        json={"location": "garage"},
    )
    assert resp.status_code == 404


def test_delete_item(client):
    created = client.post(
        "/api/v1/community/items", json={"name": "Drill"}
    ).json()
    resp = client.delete(f"/api/v1/community/items/{created['id']}")
    assert resp.status_code == 200
    assert client.get("/api/v1/community/items").json() == []
