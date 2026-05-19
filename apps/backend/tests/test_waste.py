"""Tests for waste logging + savings rollup."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.db import SessionLocal
from app.main import app
from app.models.core import Event
from app.models.food import FoodWasteEvent, Ingredient, PantryItem


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def pantry_lettuce():
    """Pantry has 1 head of lettuce ($2 estimated value)."""
    with SessionLocal() as db:
        lettuce = db.query(Ingredient).filter_by(canonical_name="lettuce").one()
        item = PantryItem(
            household_id=DEV_HOUSEHOLD_ID,
            ingredient_id=lettuce.id,
            raw_name="lettuce",
            quantity=1.0,
            unit="head",
            estimated_value=2.0,
            source="manual",
            expires_at=date.today() + timedelta(days=1),
        )
        db.add(item)
        db.commit()
        return str(item.id)


def test_post_waste_soft_deletes_pantry_and_emits(client, pantry_lettuce):
    resp = client.post(
        "/api/v1/food/waste",
        json={
            "pantry_item_id": pantry_lettuce,
            "ingredient_name": "lettuce",
            "quantity": 1.0,
            "unit": "head",
            "reason": "spoiled",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ingredient_name"] == "lettuce"
    assert body["reason"] == "spoiled"
    # Pulled value from linked pantry item
    assert body["estimated_value_usd"] == 2.0

    with SessionLocal() as db:
        pantry = (
            db.query(PantryItem).filter_by(id=pantry_lettuce).one()
        )
        assert pantry.deleted_at is not None  # soft-deleted because full quantity wasted

        events = (
            db.query(Event)
            .filter(Event.event_type == "food.pantry_item.wasted")
            .all()
        )
        assert len(events) == 1
        assert events[0].payload["estimated_value_usd"] == 2.0


def test_post_waste_partial_decrements(client):
    """Partial waste (qty < pantry qty) decrements but doesn't delete."""
    with SessionLocal() as db:
        rice = db.query(Ingredient).filter_by(canonical_name="rice").one()
        item = PantryItem(
            household_id=DEV_HOUSEHOLD_ID,
            ingredient_id=rice.id,
            raw_name="rice",
            quantity=2.0,
            unit="lb",
            source="manual",
        )
        db.add(item)
        db.commit()
        item_id = str(item.id)

    resp = client.post(
        "/api/v1/food/waste",
        json={
            "pantry_item_id": item_id,
            "ingredient_name": "rice",
            "quantity": 0.5,
            "unit": "lb",
            "reason": "spoiled",
        },
    )
    assert resp.status_code == 200

    with SessionLocal() as db:
        p = db.query(PantryItem).filter_by(id=item_id).one()
        assert p.deleted_at is None
        assert float(p.quantity) == 1.5


def test_post_waste_works_without_pantry_link(client):
    """Logging waste without a pantry item id should succeed (manual entry)."""
    resp = client.post(
        "/api/v1/food/waste",
        json={
            "ingredient_name": "leftover soup",
            "quantity": 1,
            "unit": "container",
            "reason": "forgotten",
            "estimated_value_usd": 3.50,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["pantry_item_id"] is None
    assert body["estimated_value_usd"] == 3.50


def test_savings_rollup_computes_net(client):
    """Synthesize a few cooked and wasted events; check the rollup math."""
    with SessionLocal() as db:
        now = datetime.now(UTC)
        for value in [5.0, 8.0, 4.0]:
            db.add(
                Event(
                    household_id=DEV_HOUSEHOLD_ID,
                    user_id=DEV_USER_ID,
                    event_type="food.meal.cooked",
                    entity_type="recipe",
                    entity_id=None,
                    payload={"estimated_value_usd": value, "recipe_name": "Test"},
                    created_at=now - timedelta(days=2),
                )
            )
        for value in [1.5, 0.75]:
            db.add(
                Event(
                    household_id=DEV_HOUSEHOLD_ID,
                    user_id=DEV_USER_ID,
                    event_type="food.pantry_item.wasted",
                    entity_type="food_waste_event",
                    entity_id=None,
                    payload={"estimated_value_usd": value, "ingredient_name": "x"},
                    created_at=now - timedelta(days=5),
                )
            )
        db.commit()

    resp = client.get("/api/v1/food/waste/savings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["cooked_meals_count"] == 3
    assert body["waste_events_count"] == 2
    assert body["cooked_from_pantry_value_usd"] == 17.0
    assert body["waste_value_usd"] == 2.25
    assert body["net_savings_usd"] == 14.75


def test_savings_rollup_respects_period(client):
    """Events outside the period_days window should be excluded."""
    with SessionLocal() as db:
        old = datetime.now(UTC) - timedelta(days=60)
        db.add(
            Event(
                household_id=DEV_HOUSEHOLD_ID,
                event_type="food.meal.cooked",
                entity_type="recipe",
                entity_id=None,
                payload={"estimated_value_usd": 100.0},
                created_at=old,
            )
        )
        db.commit()
    resp = client.get("/api/v1/food/waste/savings?period_days=30")
    assert resp.status_code == 200
    assert resp.json()["cooked_from_pantry_value_usd"] == 0
    # With a wider window, the old event counts
    resp = client.get("/api/v1/food/waste/savings?period_days=90")
    assert resp.status_code == 200
    assert resp.json()["cooked_from_pantry_value_usd"] == 100.0


def test_savings_rollup_includes_expiring_soon(client, pantry_lettuce):
    """Items expiring within 3 days should appear in expiring_soon."""
    resp = client.get("/api/v1/food/waste/savings")
    assert resp.status_code == 200
    body = resp.json()
    raw_names = [i["raw_name"] for i in body["expiring_soon"]]
    assert "lettuce" in raw_names


def test_food_waste_event_persisted(client, pantry_lettuce):
    client.post(
        "/api/v1/food/waste",
        json={
            "pantry_item_id": pantry_lettuce,
            "ingredient_name": "lettuce",
            "quantity": 1.0,
            "unit": "head",
        },
    )
    with SessionLocal() as db:
        events = db.query(FoodWasteEvent).filter_by(
            household_id=DEV_HOUSEHOLD_ID
        ).all()
        assert len(events) == 1
        assert events[0].ingredient_name == "lettuce"
