"""Tests for ingredient seeding + resolution.

The starter catalog is seeded session-wide by conftest.py; tests query against
that pre-existing data using the rollback-per-test `db` fixture.
"""
from __future__ import annotations

import pytest

from app.db import SessionLocal
from app.models.food import Ingredient
from app.services.ingredients import (
    STARTER_INGREDIENTS,
    resolve_ingredient,
    seed_starter_ingredients,
)


def test_seed_starter_ingredients_is_idempotent():
    """Calling the seeder a second time must not duplicate rows."""
    with SessionLocal() as db:
        before = db.query(Ingredient).count()
        inserted = seed_starter_ingredients(db)
        after = db.query(Ingredient).count()
        assert inserted == 0
        assert after == before
        assert after >= len(STARTER_INGREDIENTS)


@pytest.mark.parametrize(
    "raw_name,expected_canonical",
    [
        ("tomato", "tomato"),
        ("Tomato", "tomato"),
        ("TOMATOES", "tomato"),
        ("roma tomato", "tomato"),
        ("Roma Tomatoes", "tomato"),
        ("evoo", "olive oil"),
        ("extra virgin olive oil", "olive oil"),
        ("chicken breast", "chicken"),
        ("ground beef", "beef"),
        ("garbanzo beans", "chickpeas"),
        ("kosher salt", "salt"),
        ("large eggs", "egg"),
        ("yellow onion", "onion"),
        ("spaghetti", "pasta"),
        ("jasmine rice", "rice"),
    ],
)
def test_resolve_ingredient_matches(db, raw_name, expected_canonical):
    ingredient_id = resolve_ingredient(db, raw_name)
    assert ingredient_id is not None, f"failed to resolve {raw_name!r}"
    matched = db.get(Ingredient, ingredient_id)
    assert matched.canonical_name == expected_canonical


def test_resolve_ingredient_returns_none_for_unknown(db):
    assert resolve_ingredient(db, "dragonfruit") is None
    assert resolve_ingredient(db, "asdfqwerty") is None


def test_resolve_ingredient_handles_empty(db):
    assert resolve_ingredient(db, "") is None
    assert resolve_ingredient(db, "   ") is None
