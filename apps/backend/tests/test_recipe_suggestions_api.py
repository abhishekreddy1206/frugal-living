"""End-to-end tests for the recipe-suggestions and enrich endpoints."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth import DEV_HOUSEHOLD_ID
from app.db import SessionLocal
from app.main import app
from app.models.content import ContentItem
from app.models.food import Ingredient, PantryItem
from app.schemas.content import VideoIngredients
from app.services import llm


@pytest.fixture
def client():
    return TestClient(app)


def _seed_pantry_and_video():
    with SessionLocal() as db:
        tomato = db.query(Ingredient.id).filter(Ingredient.canonical_name == "tomato").scalar()
        db.add(
            PantryItem(
                household_id=DEV_HOUSEHOLD_ID,
                ingredient_id=tomato,
                raw_name="tomatoes",
                expires_at=date.today() + timedelta(days=1),
            )
        )
        db.add(
            ContentItem(
                provider="youtube",
                external_id="sug1",
                title="Tomato Soup",
                metadata_={
                    "ingredient_ids": [str(tomato)],
                    "is_recipe_video": True,
                    "enrichment": {"version": 1, "enriched_at": "2026-05-21T00:00:00+00:00"},
                },
            )
        )
        db.commit()


def test_recipe_suggestions_returns_pantry_matches(client):
    _seed_pantry_and_video()
    resp = client.get("/api/v1/content/recipe-suggestions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pantry_size"] == 1
    assert len(body["suggestions"]) == 1
    assert body["suggestions"][0]["title"] == "Tomato Soup"
    assert "tomato" in body["suggestions"][0]["match_reason"].lower()


def test_recipe_suggestions_empty_when_no_pantry(client):
    resp = client.get("/api/v1/content/recipe-suggestions")
    assert resp.status_code == 200
    assert resp.json() == {"suggestions": [], "pantry_size": 0}


def test_enrich_endpoint_processes_pending(client, monkeypatch):
    monkeypatch.setattr(
        llm,
        "extract_video_ingredients",
        lambda title, description, tags: VideoIngredients(
            is_recipe_video=True, dish_name=None, ingredients=["rice"]
        ),
    )
    with SessionLocal() as db:
        db.add(ContentItem(provider="youtube", external_id="raw9", title="Rice Bowl", body="rice"))
        db.commit()
    resp = client.post("/api/v1/content/enrich")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enriched"] == 1
    assert body["remaining"] == 0
