"""
Meal-plan persistence — turn AIWeekPlan output into MealPlan + PlannedMeal rows.

A household has at most one `active` meal plan at any time. Generating a new
plan archives the previous active one. Drafts (if any) are left alone — they
represent unfinished work, not history.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session, selectinload

from app.models.core import Household, User
from app.models.food import MealPlan, PlannedMeal, Recipe
from app.schemas.food import AIWeekPlan, WeekPlanConstraints
from app.services.events import emit_event
from app.services.recipes import create_recipe_from_ai


def _archive_prior_active(db: Session, household: Household) -> None:
    active = (
        db.query(MealPlan)
        .filter(
            MealPlan.household_id == household.id,
            MealPlan.status == "active",
            MealPlan.deleted_at.is_(None),
        )
        .all()
    )
    for plan in active:
        plan.status = "archived"
    if active:
        db.flush()


def create_meal_plan_from_ai(
    db: Session,
    *,
    household: Household,
    user: User | None,
    ai_plan: AIWeekPlan,
    constraints: WeekPlanConstraints,
) -> MealPlan:
    """Persist an AIWeekPlan, archiving any prior active plan. Emits food.meal_plan.created."""
    _archive_prior_active(db, household)

    plan = MealPlan(
        household_id=household.id,
        week_start=constraints.week_start,
        name=None,
        target_budget_usd=constraints.target_budget_usd,
        status="active",
        metadata_={
            "pantry_coverage_summary": ai_plan.pantry_coverage_summary,
            "total_estimated_cost_usd": ai_plan.total_estimated_cost_usd,
            "dinners_per_week": constraints.dinners_per_week,
            "dietary_constraints": list(constraints.dietary_constraints),
        },
    )
    db.add(plan)
    db.flush()

    for slot in ai_plan.meals:
        recipe = create_recipe_from_ai(
            db, household=household, user=user, ai_recipe=slot.recipe
        )
        db.add(
            PlannedMeal(
                meal_plan_id=plan.id,
                recipe_id=recipe.id,
                planned_date=slot.planned_date,
                meal_type=slot.meal_type,
                servings=slot.recipe.servings,
                status="planned",
                notes=slot.rationale,
            )
        )
    db.flush()

    emit_event(
        db,
        event_type="food.meal_plan.created",
        household_id=household.id,
        user_id=user.id if user else None,
        entity_type="meal_plan",
        entity_id=plan.id,
        payload={
            "week_start": plan.week_start.isoformat(),
            "meal_count": len(ai_plan.meals),
            "target_budget_usd": float(plan.target_budget_usd)
            if plan.target_budget_usd is not None
            else None,
            "total_estimated_cost_usd": ai_plan.total_estimated_cost_usd,
        },
    )
    return plan


def load_active_plan(db: Session, household: Household) -> MealPlan | None:
    """Active plan with planned meals eagerly loaded.

    PlannedMeal has no `recipe` relationship (only an FK column), so recipe rows
    are fetched separately by the caller (see `load_plan_recipes_map`).
    """
    return (
        db.query(MealPlan)
        .options(selectinload(MealPlan.meals))
        .filter(
            MealPlan.household_id == household.id,
            MealPlan.status == "active",
            MealPlan.deleted_at.is_(None),
        )
        .order_by(MealPlan.week_start.desc())
        .first()
    )


def load_plan_recipes_map(
    db: Session, plan: MealPlan
) -> dict[uuid.UUID, Recipe]:
    """Bulk-load recipes referenced by a plan's meals, keyed by recipe.id."""
    ids = [m.recipe_id for m in plan.meals if m.recipe_id is not None]
    if not ids:
        return {}
    rows = (
        db.query(Recipe)
        .options(selectinload(Recipe.ingredients), selectinload(Recipe.steps))
        .filter(Recipe.id.in_(ids), Recipe.deleted_at.is_(None))
        .all()
    )
    return {r.id: r for r in rows}


def get_planned_meal(db: Session, planned_meal_id: uuid.UUID) -> PlannedMeal | None:
    return (
        db.query(PlannedMeal)
        .filter(PlannedMeal.id == planned_meal_id)
        .one_or_none()
    )


def mark_planned_meal_status(
    planned_meal: PlannedMeal, status: str
) -> None:
    """Update planned meal status; sets `updated_at` via SQLAlchemy onupdate."""
    planned_meal.status = status
    # Touch updated_at explicitly to be safe across drivers
    planned_meal.updated_at = datetime.now(UTC)
