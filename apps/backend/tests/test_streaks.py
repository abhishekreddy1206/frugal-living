"""Tests for streaks + badges."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth import DEV_HOUSEHOLD_ID
from app.db import SessionLocal
from app.main import app
from app.models.core import Event
from app.models.tracking import BadgeAward, BadgeDefinition, Streak
from app.services.streaks import (
    BADGE_CATALOG,
    evaluate_badges,
    recompute_streaks,
    seed_badge_definitions,
)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_tracking():
    """Reset tracking + cooked events before each test."""
    with SessionLocal() as db:
        db.query(BadgeAward).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        db.query(Streak).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        db.commit()
    yield


def _seed_cooked_events(days_offsets: list[int]):
    """Insert a cooked event for each offset (days before today)."""
    with SessionLocal() as db:
        now = datetime.now(UTC)
        for offset in days_offsets:
            db.add(
                Event(
                    household_id=DEV_HOUSEHOLD_ID,
                    event_type="food.meal.cooked",
                    entity_type="recipe",
                    entity_id=None,
                    payload={"estimated_value_usd": 5.0},
                    created_at=now - timedelta(days=offset),
                )
            )
        db.commit()


def _seed_event(event_type: str, days_offsets: list[int], payload: dict | None = None):
    with SessionLocal() as db:
        now = datetime.now(UTC)
        for offset in days_offsets:
            db.add(
                Event(
                    household_id=DEV_HOUSEHOLD_ID,
                    event_type=event_type,
                    entity_type="x",
                    entity_id=None,
                    payload=payload or {},
                    created_at=now - timedelta(days=offset),
                )
            )
        db.commit()


def test_seed_badge_definitions_is_idempotent():
    with SessionLocal() as db:
        seed_badge_definitions(db)
        second = seed_badge_definitions(db)
        assert second == 0
        count = db.query(BadgeDefinition).count()
        assert count >= len(BADGE_CATALOG)


def test_streaks_endpoint_returns_three_kinds(client):
    resp = client.get("/api/v1/tracking/streaks")
    assert resp.status_code == 200
    kinds = {s["kind"] for s in resp.json()}
    assert kinds == {"cooked_from_pantry", "zero_waste_week", "meal_planned_week"}


def test_cooked_from_pantry_streak_counts_consecutive_days(client):
    # 5 consecutive days ending today
    _seed_cooked_events([0, 1, 2, 3, 4])
    resp = client.get("/api/v1/tracking/streaks").json()
    cooked = next(s for s in resp if s["kind"] == "cooked_from_pantry")
    assert cooked["current_length"] == 5
    assert cooked["longest_length"] == 5


def test_cooked_from_pantry_streak_breaks_on_gap(client):
    # 3 days ending today + an older streak of 4 days separated by a gap
    _seed_cooked_events([0, 1, 2] + [10, 11, 12, 13])
    resp = client.get("/api/v1/tracking/streaks").json()
    cooked = next(s for s in resp if s["kind"] == "cooked_from_pantry")
    assert cooked["current_length"] == 3
    assert cooked["longest_length"] == 4


def test_meal_plan_streak_counts_recent_weeks(client):
    # Plans in last week + 2 weeks ago + 4 weeks ago (gap at week 3)
    _seed_event("food.meal_plan.created", [1, 8, 30])
    resp = client.get("/api/v1/tracking/streaks").json()
    plan = next(s for s in resp if s["kind"] == "meal_planned_week")
    # Last week and 2 weeks ago = 2 consecutive weeks covered; week 3 misses
    assert plan["current_length"] == 2


def test_first_meal_badge_awarded_on_one_cooked(client):
    _seed_cooked_events([1])
    resp = client.get("/api/v1/tracking/badges")
    assert resp.status_code == 200
    keys = {b["key"] for b in resp.json()}
    assert "first_meal_cooked" in keys


def test_week_long_badge_awarded_at_seven_cooked_days(client):
    _seed_cooked_events([0, 1, 2, 3, 4, 5, 6])
    resp = client.get("/api/v1/tracking/badges").json()
    keys = {b["key"] for b in resp}
    assert "week_cooked" in keys
    assert "first_meal_cooked" in keys


def test_badge_not_double_awarded(client):
    _seed_cooked_events([1])
    client.get("/api/v1/tracking/badges")
    client.get("/api/v1/tracking/badges")
    with SessionLocal() as db:
        first_meal_def = (
            db.query(BadgeDefinition).filter_by(key="first_meal_cooked").one()
        )
        awards = (
            db.query(BadgeAward)
            .filter_by(
                household_id=DEV_HOUSEHOLD_ID,
                badge_definition_id=first_meal_def.id,
            )
            .all()
        )
        assert len(awards) == 1


def test_zero_waste_streak_counts_weeks_with_no_waste(client):
    # No waste events anywhere → expect a big current streak
    resp = client.get("/api/v1/tracking/streaks").json()
    zw = next(s for s in resp if s["kind"] == "zero_waste_week")
    assert zw["current_length"] >= 1


def test_zero_waste_streak_breaks_on_recent_waste(client):
    # Waste yesterday → current streak should be 0
    _seed_event("food.pantry_item.wasted", [1])
    resp = client.get("/api/v1/tracking/streaks").json()
    zw = next(s for s in resp if s["kind"] == "zero_waste_week")
    assert zw["current_length"] == 0


def test_evaluate_badges_persists_streak_recompute(client):
    """Calling /badges should recompute streaks as a side effect."""
    _seed_cooked_events([0, 1])
    with SessionLocal() as db:
        # No streak row yet
        existing = (
            db.query(Streak)
            .filter_by(household_id=DEV_HOUSEHOLD_ID, kind="cooked_from_pantry")
            .one_or_none()
        )
        assert existing is None
    client.get("/api/v1/tracking/badges")
    with SessionLocal() as db:
        s = (
            db.query(Streak)
            .filter_by(household_id=DEV_HOUSEHOLD_ID, kind="cooked_from_pantry")
            .one()
        )
        assert s.current_length == 2


def test_recompute_streaks_directly(db):
    """Service-level test to lock in the math without going through endpoints."""
    from app.models.core import Household

    household = db.get(Household, DEV_HOUSEHOLD_ID)
    now = datetime.now(UTC)
    for offset in [0, 1, 2]:
        db.add(
            Event(
                household_id=DEV_HOUSEHOLD_ID,
                event_type="food.meal.cooked",
                entity_type="recipe",
                entity_id=None,
                payload={},
                created_at=now - timedelta(days=offset),
            )
        )
    db.flush()
    streaks = recompute_streaks(db, household)
    cooked = next(s for s in streaks if s.kind == "cooked_from_pantry")
    assert cooked.current_length == 3
    # Re-run to verify upsert behaviour
    streaks2 = recompute_streaks(db, household)
    assert all(s.id is not None for s in streaks2)


def test_evaluate_badges_service_level(db):
    from app.models.core import Household

    household = db.get(Household, DEV_HOUSEHOLD_ID)
    now = datetime.now(UTC)
    db.add(
        Event(
            household_id=DEV_HOUSEHOLD_ID,
            event_type="food.meal.cooked",
            entity_type="recipe",
            entity_id=None,
            payload={},
            created_at=now,
        )
    )
    db.flush()
    awarded = evaluate_badges(db, household, None)
    keys_awarded = {a.badge_definition_id for a in awarded}
    assert len(keys_awarded) >= 1
