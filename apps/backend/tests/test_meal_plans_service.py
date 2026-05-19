"""Tests for app.services.meal_plans."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.core import Event, Household, User
from app.models.food import MealPlan, PlannedMeal
from app.schemas.food import (
    AIPlannedMeal,
    AIRecipe,
    AIRecipeIngredient,
    AIRecipeStep,
    AIWeekPlan,
    WeekPlanConstraints,
)
from app.services.meal_plans import (
    create_meal_plan_from_ai,
    load_active_plan,
    load_plan_recipes_map,
)


@pytest.fixture
def household(db) -> Household:
    return db.get(Household, DEV_HOUSEHOLD_ID)


@pytest.fixture
def user(db) -> User:
    return db.get(User, DEV_USER_ID)


def _ai_recipe(name: str) -> AIRecipe:
    return AIRecipe(
        name=name,
        servings=4,
        difficulty="easy",
        ingredients=[AIRecipeIngredient(raw_name="rice", quantity=0.5, unit="lb")],
        steps=[AIRecipeStep(content="Cook rice.")],
        pantry_items_used=["rice"],
    )


def _ai_plan(week_start: date, count: int = 3) -> AIWeekPlan:
    return AIWeekPlan(
        meals=[
            AIPlannedMeal(
                planned_date=week_start + timedelta(days=i),
                meal_type="dinner",
                recipe=_ai_recipe(f"Day {i+1} Recipe"),
                rationale=f"Uses rice for day {i+1}.",
            )
            for i in range(count)
        ],
        total_estimated_cost_usd=12.50,
        pantry_coverage_summary="Uses 3 of 5 pantry items.",
    )


def test_create_meal_plan_persists_plan_and_meals(db, household, user):
    monday = date(2026, 6, 1)
    plan = create_meal_plan_from_ai(
        db,
        household=household,
        user=user,
        ai_plan=_ai_plan(monday, count=3),
        constraints=WeekPlanConstraints(
            week_start=monday, target_budget_usd=40.0, dinners_per_week=3
        ),
    )
    db.flush()

    persisted = db.get(MealPlan, plan.id)
    assert persisted is not None
    assert persisted.status == "active"
    assert persisted.week_start == monday
    assert float(persisted.target_budget_usd) == 40.0
    assert persisted.metadata_["pantry_coverage_summary"] == "Uses 3 of 5 pantry items."

    meals = db.query(PlannedMeal).filter_by(meal_plan_id=plan.id).all()
    assert len(meals) == 3
    dates = sorted(m.planned_date for m in meals)
    assert dates == [monday, monday + timedelta(days=1), monday + timedelta(days=2)]
    assert all(m.status == "planned" for m in meals)
    assert all(m.recipe_id is not None for m in meals)

    # Event emitted
    events = (
        db.query(Event)
        .filter(Event.event_type == "food.meal_plan.created", Event.entity_id == plan.id)
        .all()
    )
    assert len(events) == 1
    assert events[0].payload["meal_count"] == 3


def test_create_meal_plan_archives_prior_active(db, household, user):
    monday = date(2026, 6, 1)
    next_monday = monday + timedelta(days=7)

    first = create_meal_plan_from_ai(
        db, household=household, user=user, ai_plan=_ai_plan(monday, 1),
        constraints=WeekPlanConstraints(week_start=monday, dinners_per_week=1),
    )
    db.flush()
    second = create_meal_plan_from_ai(
        db, household=household, user=user, ai_plan=_ai_plan(next_monday, 1),
        constraints=WeekPlanConstraints(week_start=next_monday, dinners_per_week=1),
    )
    db.flush()

    db.refresh(first)
    db.refresh(second)
    assert first.status == "archived"
    assert second.status == "active"

    actives = db.query(MealPlan).filter_by(
        household_id=household.id, status="active"
    ).all()
    assert len(actives) == 1
    assert actives[0].id == second.id


def test_load_active_plan_returns_meals(db, household, user):
    monday = date(2026, 6, 1)
    plan = create_meal_plan_from_ai(
        db, household=household, user=user, ai_plan=_ai_plan(monday, 2),
        constraints=WeekPlanConstraints(week_start=monday, dinners_per_week=2),
    )
    db.flush()

    loaded = load_active_plan(db, household)
    assert loaded is not None
    assert loaded.id == plan.id
    assert len(loaded.meals) == 2


def test_load_active_plan_returns_none_when_no_active(db, household):
    assert load_active_plan(db, household) is None


def test_load_plan_recipes_map(db, household, user):
    monday = date(2026, 6, 1)
    create_meal_plan_from_ai(
        db, household=household, user=user, ai_plan=_ai_plan(monday, 2),
        constraints=WeekPlanConstraints(week_start=monday, dinners_per_week=2),
    )
    db.flush()
    loaded = load_active_plan(db, household)
    assert loaded is not None
    recipes_map = load_plan_recipes_map(db, loaded)
    assert len(recipes_map) == 2
    # Every meal's recipe_id resolves
    for meal in loaded.meals:
        assert meal.recipe_id in recipes_map
        assert len(recipes_map[meal.recipe_id].ingredients) == 1
        assert len(recipes_map[meal.recipe_id].steps) == 1
