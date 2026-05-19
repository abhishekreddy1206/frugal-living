"""End-to-end tests for the recipe stretch + cooked endpoints."""
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
from app.models.food import Ingredient, PantryItem
from app.services import llm


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_anthropic(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    return fake


def _stretch_response(recipes: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps({"recipes": recipes}))]
    )


@pytest.fixture
def pantry_with_rice_and_garlic():
    """Seed the dev household pantry with rice + garlic so the stretch call has context."""
    with SessionLocal() as db:
        rice = db.query(Ingredient).filter_by(canonical_name="rice").one()
        garlic = db.query(Ingredient).filter_by(canonical_name="garlic").one()
        db.add(PantryItem(
            household_id=DEV_HOUSEHOLD_ID,
            ingredient_id=rice.id,
            raw_name="rice", quantity=2.0, unit="lb", source="manual",
        ))
        db.add(PantryItem(
            household_id=DEV_HOUSEHOLD_ID,
            ingredient_id=garlic.id,
            raw_name="garlic", quantity=1.0, unit="head", source="manual",
        ))
        db.commit()


def _make_recipe_payload(name: str, ingredients: list[dict] | None = None) -> dict:
    return {
        "name": name,
        "description": f"{name} description",
        "servings": 4,
        "prep_time_min": 10,
        "cook_time_min": 20,
        "cuisine": "Italian",
        "difficulty": "easy",
        "tags": ["weeknight"],
        "estimated_cost_usd": 3.0,
        "estimated_cost_per_serving_usd": 0.75,
        "ingredients": ingredients or [
            {
                "raw_name": "rice",
                "quantity": 0.5,
                "unit": "lb",
                "is_optional": False,
                "substitutions": [],
            },
            {
                "raw_name": "garlic",
                "quantity": 2,
                "unit": "clove",
                "is_optional": False,
                "substitutions": [],
            },
        ],
        "steps": [
            {"content": "Boil rice.", "duration_seconds": 1200},
            {"content": "Sauté garlic."},
        ],
        "pantry_items_used": ["rice", "garlic"],
    }


def test_stretch_endpoint_persists_recipes_and_returns_them(
    client, mock_anthropic, pantry_with_rice_and_garlic
):
    mock_anthropic.messages.create.return_value = _stretch_response(
        [
            _make_recipe_payload("Garlic Rice"),
            _make_recipe_payload("Rice Pilaf"),
        ]
    )

    resp = client.get("/api/v1/food/recipes/stretch?count=2")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pantry_size"] == 2
    assert len(body["recipes"]) == 2
    assert body["recipes"][0]["name"] == "Garlic Rice"
    assert body["recipes"][0]["is_ai_generated"] is True
    assert len(body["recipes"][0]["ingredients"]) == 2
    assert body["recipes"][0]["ingredients"][0]["raw_name"] == "rice"

    # food.recipe.generated event emitted per recipe
    with SessionLocal() as db:
        events = (
            db.query(Event)
            .filter(Event.event_type == "food.recipe.generated")
            .all()
        )
        assert len(events) == 2

    # Constraint params passed through
    user_msg = mock_anthropic.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Return 2 recipes" in user_msg


def test_stretch_endpoint_passes_constraint_query_params(
    client, mock_anthropic, pantry_with_rice_and_garlic
):
    mock_anthropic.messages.create.return_value = _stretch_response([])
    resp = client.get(
        "/api/v1/food/recipes/stretch"
        "?max_prep_min=15&max_cook_min=30&meal_type=dinner&cuisines=Thai&cuisines=Mexican"
    )
    assert resp.status_code == 200
    user_msg = mock_anthropic.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "<= 15" in user_msg
    assert "<= 30" in user_msg
    assert "dinner" in user_msg
    assert "Thai" in user_msg and "Mexican" in user_msg


def test_stretch_endpoint_rejects_bad_count(client, mock_anthropic, pantry_with_rice_and_garlic):
    resp = client.get("/api/v1/food/recipes/stretch?count=99")
    assert resp.status_code == 422


def test_cooked_endpoint_decrements_pantry_and_emits_event(
    client, mock_anthropic, pantry_with_rice_and_garlic
):
    # 1. Generate recipes
    mock_anthropic.messages.create.return_value = _stretch_response(
        [_make_recipe_payload("Garlic Rice")]
    )
    stretch = client.get("/api/v1/food/recipes/stretch?count=1").json()
    recipe_id = stretch["recipes"][0]["id"]

    # 2. Mark cooked
    resp = client.post(f"/api/v1/food/recipes/{recipe_id}/cooked")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["recipe_name"] == "Garlic Rice"
    assert body["servings"] == 4
    assert body["cooked_from_pantry_pct"] == 1.0  # rice + garlic both matched
    assert len(body["decremented_item_ids"]) >= 1

    # 3. Pantry was decremented: rice 2.0 - 0.5 = 1.5 lb
    with SessionLocal() as db:
        rice_item = (
            db.query(PantryItem)
            .filter(PantryItem.household_id == DEV_HOUSEHOLD_ID,
                    PantryItem.raw_name == "rice",
                    PantryItem.deleted_at.is_(None))
            .one()
        )
        assert float(rice_item.quantity) == 1.5

        # 4. Event emitted
        cooked_events = (
            db.query(Event).filter(Event.event_type == "food.meal.cooked").all()
        )
        assert len(cooked_events) == 1
        assert cooked_events[0].payload["cooked_from_pantry_pct"] == 1.0


def test_cooked_endpoint_404_for_missing_recipe(client):
    import uuid as _u
    resp = client.post(f"/api/v1/food/recipes/{_u.uuid4()}/cooked")
    assert resp.status_code == 404


def test_cooked_endpoint_supports_partial_servings(
    client, mock_anthropic, pantry_with_rice_and_garlic
):
    mock_anthropic.messages.create.return_value = _stretch_response(
        [_make_recipe_payload("Garlic Rice")]
    )
    stretch = client.get("/api/v1/food/recipes/stretch?count=1").json()
    recipe_id = stretch["recipes"][0]["id"]

    # Cook only 2 of the 4 servings → consumes 0.25 lb rice
    resp = client.post(f"/api/v1/food/recipes/{recipe_id}/cooked?servings_cooked=2")
    assert resp.status_code == 200
    assert resp.json()["servings"] == 2

    with SessionLocal() as db:
        rice_item = (
            db.query(PantryItem)
            .filter(PantryItem.household_id == DEV_HOUSEHOLD_ID,
                    PantryItem.raw_name == "rice",
                    PantryItem.deleted_at.is_(None))
            .one()
        )
        assert float(rice_item.quantity) == 1.75  # 2.0 - (0.5 * 2/4)
