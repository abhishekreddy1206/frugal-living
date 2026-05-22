"""End-to-end tests for the chat conversation endpoints."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import DEV_HOUSEHOLD_ID
from app.db import SessionLocal
from app.main import app
from app.models.core import Event
from app.models.food import PantryItem
from app.schemas.ai import ChatAction, ChatTurnResult
from app.services import llm


@pytest.fixture
def client():
    return TestClient(app)


def test_open_conversation_creates_thread(client):
    resp = client.post("/api/v1/ai/conversations", json={"page": "/pantry"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["page"] == "pantry"
    assert body["messages"] == []
    assert uuid.UUID(body["conversation_id"])


def test_open_conversation_idempotent_per_page(client):
    first = client.post("/api/v1/ai/conversations", json={"page": "/pantry"}).json()
    second = client.post("/api/v1/ai/conversations", json={"page": "/pantry"}).json()
    assert first["conversation_id"] == second["conversation_id"]


def test_post_message_runs_turn_and_persists(client, monkeypatch):
    monkeypatch.setattr(
        llm,
        "chat_turn",
        lambda history, context, page: ChatTurnResult(
            reply="Added rice to your pantry.",
            actions=[ChatAction(type="add_pantry_item", raw_name="rice")],
        ),
    )
    conv = client.post("/api/v1/ai/conversations", json={"page": "/pantry"}).json()
    resp = client.post(
        f"/api/v1/ai/conversations/{conv['conversation_id']}/messages",
        json={"content": "add rice"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reply"] == "Added rice to your pantry."
    assert body["actions"][0]["status"] == "ok"

    with SessionLocal() as db:
        items = db.query(PantryItem).filter_by(household_id=DEV_HOUSEHOLD_ID).all()
        assert any(i.raw_name == "rice" for i in items)
        events = db.query(Event).filter_by(event_type="food.pantry_item.added").all()
        assert len(events) == 1

    # Re-opening the page returns the persisted turn.
    reopened = client.post("/api/v1/ai/conversations", json={"page": "/pantry"}).json()
    assert len(reopened["messages"]) == 2


def test_post_message_404_for_missing_conversation(client):
    resp = client.post(
        f"/api/v1/ai/conversations/{uuid.uuid4()}/messages",
        json={"content": "hi"},
    )
    assert resp.status_code == 404
