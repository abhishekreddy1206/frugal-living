"""
Shopping list aggregation + purchase flow.

generate_from_meal_plan rolls up every ingredient across every planned meal in
the plan, deduplicates by (ingredient_id or raw_name) + unit, subtracts current
pantry coverage, and writes ShoppingItem rows.

mark_purchased turns a ShoppingItem into a PantryItem and emits
food.shopping_item.purchased.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.core import Household, User
from app.models.food import (
    MealPlan,
    PantryItem,
    Recipe,
    RecipeIngredient,
    ShoppingItem,
    ShoppingList,
)
from app.services.events import emit_event


def _key_for_ingredient(ri_ingredient_id: uuid.UUID | None, raw_name: str, unit: str | None):
    """Dedup key — prefer canonical ingredient_id; fall back to raw_name normalization."""
    if ri_ingredient_id is not None:
        return ("canon", ri_ingredient_id, (unit or "").lower())
    return ("raw", raw_name.strip().lower(), (unit or "").lower())


def _archive_prior_active_list(db: Session, household: Household) -> None:
    prior = (
        db.query(ShoppingList)
        .filter(
            ShoppingList.household_id == household.id,
            ShoppingList.status == "active",
            ShoppingList.deleted_at.is_(None),
        )
        .all()
    )
    for sl in prior:
        sl.status = "archived"
    if prior:
        db.flush()


def generate_from_meal_plan(
    db: Session,
    *,
    household: Household,
    user: User | None,
    meal_plan: MealPlan,
) -> ShoppingList:
    """Aggregate planned-meal ingredients, subtract pantry coverage, write ShoppingItem rows."""
    _archive_prior_active_list(db, household)

    # Load every recipe + its ingredients in one go
    meal_recipe_ids = [m.recipe_id for m in meal_plan.meals if m.recipe_id]
    recipes = (
        db.query(Recipe)
        .filter(Recipe.id.in_(meal_recipe_ids))
        .all()
    ) if meal_recipe_ids else []
    recipes_by_id = {r.id: r for r in recipes}

    # Pull each meal's RecipeIngredient rows
    ri_rows = (
        db.query(RecipeIngredient)
        .filter(RecipeIngredient.recipe_id.in_(meal_recipe_ids))
        .all()
    ) if meal_recipe_ids else []
    ri_by_recipe: dict[uuid.UUID, list[RecipeIngredient]] = {}
    for ri in ri_rows:
        ri_by_recipe.setdefault(ri.recipe_id, []).append(ri)

    # Build {key: aggregated_qty} weighted by servings_planned / recipe_servings
    aggregated: dict[tuple, dict] = {}
    for pm in meal_plan.meals:
        if pm.recipe_id is None:
            continue
        recipe = recipes_by_id.get(pm.recipe_id)
        if recipe is None:
            continue
        ratio = (pm.servings / recipe.servings) if recipe.servings else 1.0
        for ri in ri_by_recipe.get(pm.recipe_id, []):
            if ri.is_optional:
                continue
            key = _key_for_ingredient(ri.ingredient_id, ri.raw_name, ri.unit)
            slot = aggregated.setdefault(
                key,
                {
                    "ingredient_id": ri.ingredient_id,
                    "raw_name": ri.raw_name,
                    "unit": ri.unit,
                    "needed": 0.0,
                    "quantity_known": False,
                },
            )
            if ri.quantity is not None:
                slot["needed"] += float(ri.quantity) * ratio
                slot["quantity_known"] = True

    # Subtract pantry coverage (by ingredient_id + matching unit only)
    pantry_rows: list[PantryItem] = (
        db.query(PantryItem)
        .filter(
            PantryItem.household_id == household.id,
            PantryItem.deleted_at.is_(None),
        )
        .all()
    )
    pantry_by_canon: dict[tuple, float] = {}
    for p in pantry_rows:
        if p.ingredient_id is None or p.quantity is None:
            continue
        key = ("canon", p.ingredient_id, (p.unit or "").lower())
        pantry_by_canon[key] = pantry_by_canon.get(key, 0.0) + float(p.quantity)

    # Create the ShoppingList
    sl = ShoppingList(
        household_id=household.id,
        meal_plan_id=meal_plan.id,
        name=f"Week of {meal_plan.week_start.isoformat()}",
        status="active",
        target_date=meal_plan.week_start,
        metadata_={},
    )
    db.add(sl)
    db.flush()

    for key, slot in aggregated.items():
        if slot["quantity_known"]:
            on_hand = pantry_by_canon.get(key, 0.0)
            needed = max(slot["needed"] - on_hand, 0.0)
            if needed <= 0:
                continue
        else:
            # No quantity info — only add if we have nothing canonical on hand
            if key[0] == "canon" and pantry_by_canon.get(key, 0.0) > 0:
                continue
            needed = None  # show on list with "buy what you need" semantics

        db.add(
            ShoppingItem(
                shopping_list_id=sl.id,
                ingredient_id=slot["ingredient_id"],
                raw_name=slot["raw_name"],
                quantity=needed,
                unit=slot["unit"],
                status="pending",
            )
        )

    db.flush()
    emit_event(
        db,
        event_type="food.shopping_list.generated",
        household_id=household.id,
        user_id=user.id if user else None,
        entity_type="shopping_list",
        entity_id=sl.id,
        payload={
            "meal_plan_id": str(meal_plan.id),
            "item_count": db.query(ShoppingItem)
            .filter_by(shopping_list_id=sl.id)
            .count(),
        },
    )
    return sl


def load_active_list(db: Session, household: Household) -> ShoppingList | None:
    return (
        db.query(ShoppingList)
        .filter(
            ShoppingList.household_id == household.id,
            ShoppingList.status == "active",
            ShoppingList.deleted_at.is_(None),
        )
        .order_by(ShoppingList.created_at.desc())
        .first()
    )


def mark_purchased(
    db: Session,
    *,
    household: Household,
    user: User | None,
    item: ShoppingItem,
    actual_price_usd: float | None,
    location_id: uuid.UUID | None,
) -> PantryItem:
    """Convert a ShoppingItem to a PantryItem, mark it purchased, emit event."""
    pantry_item = PantryItem(
        household_id=household.id,
        location_id=location_id,
        ingredient_id=item.ingredient_id,
        raw_name=item.raw_name,
        quantity=item.quantity,
        unit=item.unit,
        purchased_at=None,  # set to today via server default at insert
        estimated_value=actual_price_usd or item.estimated_price_usd,
        source="imported",
        confidence=None,
    )
    db.add(pantry_item)
    item.status = "purchased"
    if actual_price_usd is not None:
        item.actual_price_usd = actual_price_usd
    db.flush()

    emit_event(
        db,
        event_type="food.shopping_item.purchased",
        household_id=household.id,
        user_id=user.id if user else None,
        entity_type="shopping_item",
        entity_id=item.id,
        payload={
            "raw_name": item.raw_name,
            "actual_price_usd": float(actual_price_usd) if actual_price_usd is not None else None,
            "pantry_item_id": str(pantry_item.id),
        },
    )
    return pantry_item
