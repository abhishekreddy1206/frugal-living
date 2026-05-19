"""
Pantry mutation helpers — consuming and snapshotting.

`consume_for_recipe` is the heart of the "I cooked this" flow: it decrements
quantities of pantry items that match a recipe's resolved ingredients, soft-deletes
items that run out, and returns a coverage summary so callers can emit a meaningful
food.meal.cooked event.

Unit conversion is intentionally absent in v1 — units must match (case-insensitive)
for the decrement to apply. Mismatches still count toward coverage but skip the
arithmetic. The trade-off is conservative correctness over false confidence.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import asc, nulls_last
from sqlalchemy.orm import Session

from app.models.core import Household
from app.models.food import PantryItem, Recipe, RecipeIngredient
from app.schemas.food import PantrySnapshotItem


@dataclass
class CookResult:
    matched_count: int
    total_ingredients: int
    decremented_item_ids: list[uuid.UUID] = field(default_factory=list)
    estimated_value_usd: float | None = None

    @property
    def cooked_from_pantry_pct(self) -> float:
        if self.total_ingredients == 0:
            return 0.0
        return round(self.matched_count / self.total_ingredients, 4)


def snapshot_pantry(db: Session, household: Household) -> list[PantrySnapshotItem]:
    """Compact pantry view for prompts — ordered by soonest-expiring first."""
    rows: list[PantryItem] = (
        db.query(PantryItem)
        .filter(
            PantryItem.household_id == household.id,
            PantryItem.deleted_at.is_(None),
        )
        .order_by(nulls_last(asc(PantryItem.expires_at)), PantryItem.created_at.desc())
        .all()
    )
    today = date.today()
    out = []
    for r in rows:
        if r.expires_at is not None:
            days = (r.expires_at - today).days
        else:
            days = None
        out.append(
            PantrySnapshotItem(
                raw_name=r.raw_name,
                quantity=float(r.quantity) if r.quantity is not None else None,
                unit=r.unit,
                expires_in_days=days,
                ingredient_id=r.ingredient_id,
            )
        )
    return out


def _units_match(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return False
    return a.strip().lower() == b.strip().lower()


def consume_for_recipe(
    db: Session,
    *,
    household: Household,
    recipe: Recipe,
    servings_cooked: int,
) -> CookResult:
    """Decrement pantry quantities for resolved recipe ingredients.

    Coverage rule: a recipe ingredient counts as "matched" if the household has
    any non-deleted pantry item with the same ingredient_id, regardless of unit.
    Decrement rule: only when units match and both quantities are present.
    """
    # Query directly rather than relying on the relationship — that collection
    # may be stale (cached empty) if the recipe was created in this same session.
    ingredients: list[RecipeIngredient] = (
        db.query(RecipeIngredient).filter_by(recipe_id=recipe.id).all()
    )
    if not ingredients:
        return CookResult(matched_count=0, total_ingredients=0)

    serving_ratio = (
        servings_cooked / recipe.servings if recipe.servings else 1.0
    )

    result = CookResult(matched_count=0, total_ingredients=len(ingredients))
    estimated_value_total = 0.0

    for ri in ingredients:
        if ri.ingredient_id is None:
            continue

        # Find pantry items for this ingredient, oldest expiry first.
        candidates: list[PantryItem] = (
            db.query(PantryItem)
            .filter(
                PantryItem.household_id == household.id,
                PantryItem.ingredient_id == ri.ingredient_id,
                PantryItem.deleted_at.is_(None),
            )
            .order_by(
                nulls_last(asc(PantryItem.expires_at)),
                asc(PantryItem.created_at),
            )
            .all()
        )
        if not candidates:
            continue

        result.matched_count += 1

        need = (
            float(ri.quantity) * serving_ratio
            if ri.quantity is not None
            else None
        )

        for pantry_item in candidates:
            if need is None or need <= 0:
                break
            if pantry_item.quantity is None or not _units_match(pantry_item.unit, ri.unit):
                # Coverage counts, but we can't subtract without compatible units.
                break

            available = float(pantry_item.quantity)
            consumed = min(available, need)
            new_qty = available - consumed
            pantry_item.quantity = new_qty
            if pantry_item.estimated_value is not None and available > 0:
                estimated_value_total += float(pantry_item.estimated_value) * (
                    consumed / available
                )
            if new_qty <= 0:
                pantry_item.deleted_at = datetime.now(UTC)
            result.decremented_item_ids.append(pantry_item.id)
            need -= consumed

    if estimated_value_total > 0:
        result.estimated_value_usd = round(estimated_value_total, 2)

    db.flush()
    return result
