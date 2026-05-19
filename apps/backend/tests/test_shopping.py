"""Tests for the shopping list service + endpoints."""
from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.auth import DEV_HOUSEHOLD_ID
from app.db import SessionLocal
from app.main import app
from app.models.core import Event
from app.models.food import Ingredient, PantryItem, ShoppingItem, ShoppingList
from app.services import llm


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_anthropic(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    return fake


def _plan_response(meals: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text",
                text=json.dumps(
                    {
                        "meals": meals,
                        "total_estimated_cost_usd": 10.0,
                        "pantry_coverage_summary": "summary",
                    }
                ),
            )
        ]
    )


def _recipe(name: str, ingredients: list[dict]) -> dict:
    return {
        "name": name,
        "description": None,
        "servings": 4,
        "prep_time_min": 10,
        "cook_time_min": 20,
        "cuisine": "Italian",
        "difficulty": "easy",
        "tags": [],
        "estimated_cost_usd": 5.0,
        "estimated_cost_per_serving_usd": 1.25,
        "ingredients": ingredients,
        "steps": [{"content": "Cook.", "duration_seconds": None}],
        "pantry_items_used": [],
    }


def _ingredient(raw_name: str, qty: float, unit: str) -> dict:
    return {
        "raw_name": raw_name,
        "quantity": qty,
        "unit": unit,
        "is_optional": False,
        "substitutions": [],
    }


@pytest.fixture
def pantry_with_rice():
    """Pantry has rice but not garlic."""
    with SessionLocal() as db:
        rice = db.query(Ingredient).filter_by(canonical_name="rice").one()
        db.add(
            PantryItem(
                household_id=DEV_HOUSEHOLD_ID,
                ingredient_id=rice.id,
                raw_name="rice",
                quantity=2.0,
                unit="lb",
                source="manual",
            )
        )
        db.commit()


def _generate_plan(client, mock_anthropic, week_start: date):
    mock_anthropic.messages.create.return_value = _plan_response(
        [
            {
                "planned_date": week_start.isoformat(),
                "meal_type": "dinner",
                "rationale": "",
                "recipe": _recipe(
                    "Rice + garlic",
                    [
                        _ingredient("rice", 1.0, "lb"),
                        _ingredient("garlic", 3, "clove"),
                    ],
                ),
            }
        ]
    )
    return client.post(
        "/api/v1/food/meal-plans/generate",
        json={"week_start": week_start.isoformat(), "dinners_per_week": 1},
    ).json()


def test_shopping_list_from_plan_subtracts_pantry(client, mock_anthropic, pantry_with_rice):
    monday = date(2026, 6, 1)
    _generate_plan(client, mock_anthropic, monday)

    resp = client.post("/api/v1/food/shopping-lists/from-plan")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "active"
    assert body["meal_plan_id"] is not None

    # Rice is in pantry (2 lb > 1 lb needed) → omitted. Garlic isn't → present.
    names = [i["raw_name"] for i in body["items"]]
    assert "garlic" in names
    assert "rice" not in names


def test_shopping_list_409_when_no_active_plan(client):
    resp = client.post("/api/v1/food/shopping-lists/from-plan")
    assert resp.status_code == 409


def test_active_shopping_list_returns_null_then_list(client, mock_anthropic, pantry_with_rice):
    monday = date(2026, 6, 1)
    resp = client.get("/api/v1/food/shopping-lists/active")
    assert resp.status_code == 200
    assert resp.json() is None

    _generate_plan(client, mock_anthropic, monday)
    client.post("/api/v1/food/shopping-lists/from-plan")

    resp = client.get("/api/v1/food/shopping-lists/active")
    assert resp.status_code == 200
    assert resp.json() is not None
    assert resp.json()["status"] == "active"


def test_generating_new_shopping_list_archives_old(client, mock_anthropic, pantry_with_rice):
    monday = date(2026, 6, 1)
    _generate_plan(client, mock_anthropic, monday)
    client.post("/api/v1/food/shopping-lists/from-plan")
    client.post("/api/v1/food/shopping-lists/from-plan")

    with SessionLocal() as db:
        actives = (
            db.query(ShoppingList)
            .filter(
                ShoppingList.household_id == DEV_HOUSEHOLD_ID,
                ShoppingList.status == "active",
            )
            .all()
        )
        assert len(actives) == 1
        archived = (
            db.query(ShoppingList)
            .filter(
                ShoppingList.household_id == DEV_HOUSEHOLD_ID,
                ShoppingList.status == "archived",
            )
            .all()
        )
        assert len(archived) == 1


def test_mark_purchased_adds_to_pantry_and_emits(client, mock_anthropic, pantry_with_rice):
    monday = date(2026, 6, 1)
    _generate_plan(client, mock_anthropic, monday)
    body = client.post("/api/v1/food/shopping-lists/from-plan").json()
    garlic_item_id = next(i for i in body["items"] if i["raw_name"] == "garlic")["id"]

    resp = client.post(
        f"/api/v1/food/shopping-items/{garlic_item_id}/purchased",
        json={"actual_price_usd": 0.79},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["status"] == "purchased"
    assert payload["pantry_item_id"] != "00000000-0000-0000-0000-000000000000"

    with SessionLocal() as db:
        # Pantry now has both rice (from fixture) and garlic (newly purchased)
        items = (
            db.query(PantryItem)
            .filter(
                PantryItem.household_id == DEV_HOUSEHOLD_ID,
                PantryItem.deleted_at.is_(None),
            )
            .all()
        )
        names = {i.raw_name for i in items}
        assert "rice" in names and "garlic" in names

        # find garlic shopping item
        garlic = (
            db.query(ShoppingItem)
            .filter(ShoppingItem.raw_name == "garlic")
            .one()
        )
        assert garlic.status == "purchased"
        assert float(garlic.actual_price_usd) == 0.79

        # Event emitted
        events = (
            db.query(Event)
            .filter(Event.event_type == "food.shopping_item.purchased")
            .all()
        )
        assert len(events) == 1


def test_mark_purchased_idempotent(client, mock_anthropic, pantry_with_rice):
    monday = date(2026, 6, 1)
    _generate_plan(client, mock_anthropic, monday)
    body = client.post("/api/v1/food/shopping-lists/from-plan").json()
    garlic_id = next(i for i in body["items"] if i["raw_name"] == "garlic")["id"]

    client.post(f"/api/v1/food/shopping-items/{garlic_id}/purchased", json={})
    resp = client.post(f"/api/v1/food/shopping-items/{garlic_id}/purchased", json={})
    assert resp.status_code == 200
    assert resp.json()["status"] == "already_purchased"

    with SessionLocal() as db:
        # Only one pantry item added (idempotency)
        garlics = (
            db.query(PantryItem)
            .filter(
                PantryItem.household_id == DEV_HOUSEHOLD_ID,
                PantryItem.raw_name == "garlic",
                PantryItem.deleted_at.is_(None),
            )
            .all()
        )
        assert len(garlics) == 1
