"""Tests for app.services.pantry — snapshot + consume_for_recipe."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.auth import DEV_HOUSEHOLD_ID
from app.models.core import Household
from app.models.food import Ingredient, PantryItem, Recipe, RecipeIngredient
from app.services.pantry import consume_for_recipe, snapshot_pantry


@pytest.fixture
def household(db) -> Household:
    return db.get(Household, DEV_HOUSEHOLD_ID)


def _get_ingredient(db, canonical: str) -> Ingredient:
    ing = db.query(Ingredient).filter_by(canonical_name=canonical).one()
    return ing


def _add_pantry_item(db, household, ingredient, raw_name, quantity, unit, expires_at=None):
    item = PantryItem(
        household_id=household.id,
        ingredient_id=ingredient.id if ingredient else None,
        raw_name=raw_name,
        quantity=quantity,
        unit=unit,
        expires_at=expires_at,
        source="manual",
    )
    db.add(item)
    db.flush()
    return item


def _make_recipe(db, ingredients_spec, servings=4):
    """Build a Recipe with given (ingredient_canonical, quantity, unit) tuples."""
    recipe = Recipe(
        name="Test Recipe",
        slug=f"test-recipe-{id(ingredients_spec)}",
        servings=servings,
        difficulty="easy",
        is_ai_generated=True,
    )
    db.add(recipe)
    db.flush()
    for canonical, qty, unit in ingredients_spec:
        ing = _get_ingredient(db, canonical) if canonical else None
        db.add(
            RecipeIngredient(
                recipe_id=recipe.id,
                ingredient_id=ing.id if ing else None,
                raw_name=canonical or "unknown",
                quantity=qty,
                unit=unit,
                is_optional=False,
                substitutions=[],
                order_index=0,
            )
        )
    db.flush()
    db.refresh(recipe)
    return recipe


def test_snapshot_pantry_orders_by_soonest_expiry(db, household):
    today = date.today()
    rice = _get_ingredient(db, "rice")
    tomato = _get_ingredient(db, "tomato")
    _add_pantry_item(db, household, rice, "rice", 1, "lb", expires_at=today + timedelta(days=365))
    _add_pantry_item(db, household, tomato, "tomato", 3, "each", expires_at=today + timedelta(days=2))
    snap = snapshot_pantry(db, household)
    assert snap[0].raw_name == "tomato"
    assert snap[0].expires_in_days == 2
    assert snap[1].raw_name == "rice"


def test_consume_for_recipe_decrements_matching_units(db, household):
    rice = _get_ingredient(db, "rice")
    item = _add_pantry_item(db, household, rice, "rice", 2.0, "lb")
    recipe = _make_recipe(db, [("rice", 0.5, "lb")], servings=4)

    result = consume_for_recipe(db, household=household, recipe=recipe, servings_cooked=4)

    db.refresh(item)
    assert result.matched_count == 1
    assert result.total_ingredients == 1
    assert result.cooked_from_pantry_pct == 1.0
    assert float(item.quantity) == 1.5
    assert item.deleted_at is None
    assert item.id in result.decremented_item_ids


def test_consume_for_recipe_half_servings(db, household):
    rice = _get_ingredient(db, "rice")
    item = _add_pantry_item(db, household, rice, "rice", 2.0, "lb")
    recipe = _make_recipe(db, [("rice", 1.0, "lb")], servings=4)
    # Cooking 2/4 servings = 0.5 lb consumed
    consume_for_recipe(db, household=household, recipe=recipe, servings_cooked=2)
    db.refresh(item)
    assert float(item.quantity) == 1.5


def test_consume_for_recipe_soft_deletes_empty(db, household):
    salt = _get_ingredient(db, "salt")
    item = _add_pantry_item(db, household, salt, "salt", 1.0, "container")
    recipe = _make_recipe(db, [("salt", 1.0, "container")], servings=4)
    consume_for_recipe(db, household=household, recipe=recipe, servings_cooked=4)
    db.refresh(item)
    assert float(item.quantity) == 0
    assert item.deleted_at is not None


def test_consume_for_recipe_skips_when_units_mismatch(db, household):
    """Pantry has 1 'bottle' of olive oil; recipe wants 2 tbsp. Coverage counts; no decrement."""
    oil = _get_ingredient(db, "olive oil")
    item = _add_pantry_item(db, household, oil, "olive oil", 1.0, "bottle")
    recipe = _make_recipe(db, [("olive oil", 2.0, "tbsp")], servings=4)
    result = consume_for_recipe(db, household=household, recipe=recipe, servings_cooked=4)
    db.refresh(item)
    assert result.matched_count == 1  # coverage counts
    assert float(item.quantity) == 1.0  # but no decrement
    assert item.id not in result.decremented_item_ids


def test_consume_for_recipe_partial_match_calculates_pct(db, household):
    """Pantry has rice; recipe needs rice + chicken + onion. Only rice matches."""
    rice = _get_ingredient(db, "rice")
    _add_pantry_item(db, household, rice, "rice", 1.0, "lb")
    recipe = _make_recipe(
        db,
        [
            ("rice", 0.5, "lb"),
            ("chicken", 1.0, "lb"),
            ("onion", 1.0, "each"),
        ],
        servings=4,
    )
    result = consume_for_recipe(db, household=household, recipe=recipe, servings_cooked=4)
    assert result.matched_count == 1
    assert result.total_ingredients == 3
    assert result.cooked_from_pantry_pct == round(1 / 3, 4)


def test_consume_for_recipe_unresolved_ingredient_skipped(db, household):
    """A recipe ingredient with ingredient_id=None contributes to total but never matches."""
    recipe = _make_recipe(db, [(None, 1, "each")], servings=4)
    result = consume_for_recipe(db, household=household, recipe=recipe, servings_cooked=4)
    assert result.matched_count == 0
    assert result.total_ingredients == 1
    assert result.cooked_from_pantry_pct == 0.0


def test_consume_for_recipe_drains_multiple_items_oldest_first(db, household):
    """Two rice items in pantry; consume should drain the soonest-expiring first."""
    rice = _get_ingredient(db, "rice")
    today = date.today()
    old = _add_pantry_item(db, household, rice, "rice", 0.5, "lb", expires_at=today + timedelta(days=10))
    new = _add_pantry_item(db, household, rice, "rice", 2.0, "lb", expires_at=today + timedelta(days=300))
    recipe = _make_recipe(db, [("rice", 1.0, "lb")], servings=4)

    consume_for_recipe(db, household=household, recipe=recipe, servings_cooked=4)
    db.refresh(old)
    db.refresh(new)
    # old (0.5 lb) drained completely; remaining 0.5 lb taken from new
    assert old.deleted_at is not None
    assert float(new.quantity) == 1.5
