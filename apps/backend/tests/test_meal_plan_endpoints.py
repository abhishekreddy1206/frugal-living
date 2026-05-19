"""End-to-end tests for the meal-plan + planned-meal endpoints."""
from __future__ import annotations

import json
import uuid as _u
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.auth import DEV_HOUSEHOLD_ID
from app.db import SessionLocal
from app.main import app
from app.models.core import Event
from app.models.food import Ingredient, MealPlan, PantryItem, PlannedMeal
from app.services import llm


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_anthropic(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    return fake


@pytest.fixture
def pantry_with_rice():
    with SessionLocal() as db:
        rice = db.query(Ingredient).filter_by(canonical_name="rice").one()
        db.add(
            PantryItem(
                household_id=DEV_HOUSEHOLD_ID,
                ingredient_id=rice.id,
                raw_name="rice",
                quantity=3.0,
                unit="lb",
                source="manual",
            )
        )
        db.commit()


def _recipe_payload(name: str, pantry_items: list[str] | None = None) -> dict:
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
        "ingredients": [
            {
                "raw_name": "rice", "quantity": 0.5, "unit": "lb",
                "is_optional": False, "substitutions": [],
            }
        ],
        "steps": [{"content": "Cook.", "duration_seconds": 900}],
        "pantry_items_used": pantry_items or ["rice"],
    }


def _plan_response(meals: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text",
                text=json.dumps(
                    {
                        "meals": meals,
                        "total_estimated_cost_usd": 15.0,
                        "pantry_coverage_summary": "Uses 5 of 5 items.",
                    }
                ),
            )
        ]
    )


def test_generate_plan_persists_and_returns_meals(client, mock_anthropic, pantry_with_rice):
    monday = date(2026, 6, 1)
    mock_anthropic.messages.create.return_value = _plan_response(
        [
            {
                "planned_date": (monday + timedelta(days=i)).isoformat(),
                "meal_type": "dinner",
                "rationale": f"Day {i+1} uses rice.",
                "recipe": _recipe_payload(f"Day {i+1} Dinner"),
            }
            for i in range(3)
        ]
    )

    resp = client.post(
        "/api/v1/food/meal-plans/generate",
        json={
            "week_start": monday.isoformat(),
            "target_budget_usd": 40.0,
            "dinners_per_week": 3,
            "dietary_constraints": ["vegetarian"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["plan"]["status"] == "active"
    assert len(body["plan"]["meals"]) == 3
    assert body["plan"]["meals"][0]["recipe"]["name"] == "Day 1 Dinner"
    assert body["pantry_coverage_summary"] == "Uses 5 of 5 items."
    assert body["total_estimated_cost_usd"] == 15.0

    # Verify model used was Opus
    kwargs = mock_anthropic.messages.create.call_args.kwargs
    assert kwargs["model"] == llm.MODEL_SMART
    assert "vegetarian" in kwargs["messages"][0]["content"]

    # food.meal_plan.created event emitted
    with SessionLocal() as db:
        events = (
            db.query(Event).filter(Event.event_type == "food.meal_plan.created").all()
        )
        assert len(events) == 1
        assert events[0].payload["meal_count"] == 3


def test_active_endpoint_returns_null_when_none(client):
    resp = client.get("/api/v1/food/meal-plans/active")
    assert resp.status_code == 200
    assert resp.json() is None


def test_active_endpoint_returns_current_plan(client, mock_anthropic, pantry_with_rice):
    monday = date(2026, 6, 1)
    mock_anthropic.messages.create.return_value = _plan_response(
        [
            {
                "planned_date": monday.isoformat(),
                "meal_type": "dinner",
                "rationale": "Rice.",
                "recipe": _recipe_payload("Rice Dinner"),
            }
        ]
    )
    client.post(
        "/api/v1/food/meal-plans/generate",
        json={"week_start": monday.isoformat(), "dinners_per_week": 1},
    )
    resp = client.get("/api/v1/food/meal-plans/active")
    assert resp.status_code == 200
    body = resp.json()
    assert body is not None
    assert body["status"] == "active"
    assert len(body["meals"]) == 1
    assert body["meals"][0]["recipe"]["name"] == "Rice Dinner"


def test_generate_plan_archives_prior_active(client, mock_anthropic, pantry_with_rice):
    monday = date(2026, 6, 1)
    next_monday = monday + timedelta(days=7)

    def make_response(week_start):
        return _plan_response(
            [
                {
                    "planned_date": week_start.isoformat(),
                    "meal_type": "dinner",
                    "rationale": "x",
                    "recipe": _recipe_payload("X"),
                }
            ]
        )

    mock_anthropic.messages.create.return_value = make_response(monday)
    client.post(
        "/api/v1/food/meal-plans/generate",
        json={"week_start": monday.isoformat(), "dinners_per_week": 1},
    )
    mock_anthropic.messages.create.return_value = make_response(next_monday)
    client.post(
        "/api/v1/food/meal-plans/generate",
        json={"week_start": next_monday.isoformat(), "dinners_per_week": 1},
    )

    with SessionLocal() as db:
        actives = (
            db.query(MealPlan)
            .filter(MealPlan.household_id == DEV_HOUSEHOLD_ID, MealPlan.status == "active")
            .all()
        )
        assert len(actives) == 1
        archived = (
            db.query(MealPlan)
            .filter(MealPlan.household_id == DEV_HOUSEHOLD_ID, MealPlan.status == "archived")
            .all()
        )
        assert len(archived) == 1


def test_status_cooked_decrements_and_emits(client, mock_anthropic, pantry_with_rice):
    monday = date(2026, 6, 1)
    mock_anthropic.messages.create.return_value = _plan_response(
        [
            {
                "planned_date": monday.isoformat(),
                "meal_type": "dinner",
                "rationale": "rice",
                "recipe": _recipe_payload("Rice"),
            }
        ]
    )
    body = client.post(
        "/api/v1/food/meal-plans/generate",
        json={"week_start": monday.isoformat(), "dinners_per_week": 1},
    ).json()
    planned_meal_id = body["plan"]["meals"][0]["id"]

    resp = client.post(
        f"/api/v1/food/planned-meals/{planned_meal_id}/status",
        json={"status": "cooked"},
    )
    assert resp.status_code == 200
    rj = resp.json()
    assert rj["new_status"] == "cooked"
    assert rj["cooked_from_pantry_pct"] == 1.0

    with SessionLocal() as db:
        # Pantry decremented: 3.0 - 0.5 = 2.5 lb
        rice_items = (
            db.query(PantryItem)
            .filter(
                PantryItem.household_id == DEV_HOUSEHOLD_ID,
                PantryItem.raw_name == "rice",
                PantryItem.deleted_at.is_(None),
            )
            .all()
        )
        assert len(rice_items) == 1
        assert float(rice_items[0].quantity) == 2.5

        # Planned meal status persisted
        pm = db.get(PlannedMeal, _u.UUID(planned_meal_id))
        assert pm.status == "cooked"

        # food.meal.cooked event
        cooked = (
            db.query(Event)
            .filter(
                Event.event_type == "food.meal.cooked",
                Event.entity_type == "planned_meal",
            )
            .all()
        )
        assert len(cooked) == 1
        assert cooked[0].payload["planned_meal_id"] == planned_meal_id


def test_status_skipped_emits_event(client, mock_anthropic, pantry_with_rice):
    monday = date(2026, 6, 1)
    mock_anthropic.messages.create.return_value = _plan_response(
        [
            {
                "planned_date": monday.isoformat(),
                "meal_type": "dinner",
                "rationale": "rice",
                "recipe": _recipe_payload("Rice"),
            }
        ]
    )
    body = client.post(
        "/api/v1/food/meal-plans/generate",
        json={"week_start": monday.isoformat(), "dinners_per_week": 1},
    ).json()
    planned_meal_id = body["plan"]["meals"][0]["id"]

    resp = client.post(
        f"/api/v1/food/planned-meals/{planned_meal_id}/status",
        json={"status": "skipped"},
    )
    assert resp.status_code == 200

    with SessionLocal() as db:
        # Pantry untouched
        rice_items = (
            db.query(PantryItem)
            .filter(
                PantryItem.household_id == DEV_HOUSEHOLD_ID,
                PantryItem.raw_name == "rice",
                PantryItem.deleted_at.is_(None),
            )
            .all()
        )
        assert float(rice_items[0].quantity) == 3.0

        events = (
            db.query(Event).filter(Event.event_type == "food.meal.skipped").all()
        )
        assert len(events) == 1


def test_status_404_for_missing_meal(client):
    resp = client.post(
        f"/api/v1/food/planned-meals/{_u.uuid4()}/status",
        json={"status": "skipped"},
    )
    assert resp.status_code == 404


def test_status_rejects_bad_status(client, mock_anthropic, pantry_with_rice):
    monday = date(2026, 6, 1)
    mock_anthropic.messages.create.return_value = _plan_response(
        [
            {
                "planned_date": monday.isoformat(),
                "meal_type": "dinner",
                "rationale": "x",
                "recipe": _recipe_payload("Rice"),
            }
        ]
    )
    body = client.post(
        "/api/v1/food/meal-plans/generate",
        json={"week_start": monday.isoformat(), "dinners_per_week": 1},
    ).json()
    planned_meal_id = body["plan"]["meals"][0]["id"]

    resp = client.post(
        f"/api/v1/food/planned-meals/{planned_meal_id}/status",
        json={"status": "demolished"},
    )
    assert resp.status_code == 422
