"""Tests for the daily briefing service + endpoints."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.auth import DEV_HOUSEHOLD_ID
from app.db import SessionLocal
from app.main import app
from app.models.ai import Briefing
from app.models.core import Event
from app.services import llm


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_anthropic(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    fake.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text",
                text=json.dumps(
                    {
                        "headline": "Two pantry items expiring this week",
                        "body_markdown": "**Expiring soon**: lettuce.\n\n**Tip**: stir-fry.",
                    }
                ),
            )
        ]
    )
    return fake


@pytest.fixture(autouse=True)
def _clean_briefings():
    with SessionLocal() as db:
        db.query(Briefing).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        db.commit()
    yield


def test_get_today_generates_when_missing(client, mock_anthropic):
    resp = client.get("/api/v1/ai/briefings/today")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["headline"] == "Two pantry items expiring this week"
    assert "stir-fry" in body["body_markdown"]
    assert body["was_read"] is False

    mock_anthropic.messages.create.assert_called_once()


def test_get_today_returns_cached_on_second_call(client, mock_anthropic):
    client.get("/api/v1/ai/briefings/today")
    client.get("/api/v1/ai/briefings/today")
    # Only ONE LLM call — the second request served from DB
    assert mock_anthropic.messages.create.call_count == 1


def test_regenerate_updates_in_place(client, mock_anthropic):
    """The unique (household_id, for_date) index forces in-place updates."""
    first = client.get("/api/v1/ai/briefings/today").json()
    mock_anthropic.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text",
                text=json.dumps({"headline": "Fresh!", "body_markdown": "new body"}),
            )
        ]
    )
    resp = client.post("/api/v1/ai/briefings/generate")
    assert resp.status_code == 200
    second = resp.json()
    # Same id (updated in place), but content changed
    assert second["id"] == first["id"]
    assert second["headline"] == "Fresh!"
    assert second["body_markdown"] == "new body"
    assert second["was_read"] is False


def test_mark_read_flips_flag(client, mock_anthropic):
    body = client.get("/api/v1/ai/briefings/today").json()
    assert body["was_read"] is False
    resp = client.post(f"/api/v1/ai/briefings/{body['id']}/read")
    assert resp.status_code == 200
    assert resp.json()["was_read"] is True


def test_mark_read_404_for_missing(client):
    import uuid as _u
    resp = client.post(f"/api/v1/ai/briefings/{_u.uuid4()}/read")
    assert resp.status_code == 404


def test_briefing_persists_in_db(client, mock_anthropic):
    client.get("/api/v1/ai/briefings/today")
    with SessionLocal() as db:
        rows = (
            db.query(Briefing)
            .filter(Briefing.household_id == DEV_HOUSEHOLD_ID, Briefing.deleted_at.is_(None))
            .all()
        )
        assert len(rows) == 1
        assert "stir-fry" in rows[0].body_markdown


def test_briefing_emits_event(client, mock_anthropic):
    client.get("/api/v1/ai/briefings/today")
    with SessionLocal() as db:
        events = (
            db.query(Event)
            .filter(Event.event_type == "ai.briefing.generated")
            .all()
        )
        assert len(events) == 1


def test_briefing_metadata_includes_savings_snapshot(client, mock_anthropic):
    # Synthesize an old cooked event so the rollup has something
    with SessionLocal() as db:
        db.add(
            Event(
                household_id=DEV_HOUSEHOLD_ID,
                event_type="food.meal.cooked",
                entity_type="recipe",
                entity_id=None,
                payload={"estimated_value_usd": 5.0},
                created_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        db.commit()
    client.get("/api/v1/ai/briefings/today")
    with SessionLocal() as db:
        b = (
            db.query(Briefing)
            .filter(Briefing.household_id == DEV_HOUSEHOLD_ID, Briefing.deleted_at.is_(None))
            .one()
        )
        assert b.metadata_["savings_net_usd"] == 5.0
