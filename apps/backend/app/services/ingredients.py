"""
Canonical ingredient catalog + raw-name resolver.

Every captured pantry item has a free-form raw_name (what the photo said).
This module resolves that string to a canonical food.ingredients row when possible,
which lets recipes, shopping lists, and waste tracking share inventory across surfaces.

The starter catalog is intentionally small (US-pantry staples) — extended over time
either by user edits or by an offline LLM-driven canonicalization job.
"""
from __future__ import annotations

import re
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.food import Ingredient

# (canonical_name, display_name, category, default_unit, shelf_life_days, aliases)
StarterRow = tuple[str, str, str, str | None, int | None, list[str]]

STARTER_INGREDIENTS: list[StarterRow] = [
    # Produce
    ("tomato", "Tomato", "produce", "each", 7, ["tomatoes", "roma tomato", "vine tomato"]),
    ("onion", "Onion", "produce", "each", 30, ["onions", "yellow onion", "white onion"]),
    ("garlic", "Garlic", "produce", "head", 30, ["garlic clove", "garlic head", "cloves"]),
    ("potato", "Potato", "produce", "each", 30, ["potatoes", "russet", "yukon"]),
    ("carrot", "Carrot", "produce", "each", 21, ["carrots"]),
    ("lemon", "Lemon", "produce", "each", 14, ["lemons"]),
    ("banana", "Banana", "produce", "each", 7, ["bananas"]),
    ("apple", "Apple", "produce", "each", 30, ["apples"]),
    ("spinach", "Spinach", "produce", "bunch", 7, ["spinach leaves", "baby spinach"]),
    ("lettuce", "Lettuce", "produce", "head", 7, ["romaine", "iceberg", "salad greens"]),
    # Dairy
    ("milk", "Milk", "dairy", "gallon", 14, ["whole milk", "2% milk", "skim milk"]),
    ("butter", "Butter", "dairy", "stick", 60, ["unsalted butter", "salted butter"]),
    ("cheese", "Cheese", "dairy", "block", 30, ["cheddar", "mozzarella", "parmesan"]),
    ("yogurt", "Yogurt", "dairy", "container", 21, ["greek yogurt", "plain yogurt"]),
    ("egg", "Egg", "protein", "each", 30, ["eggs", "large eggs"]),
    # Proteins
    ("chicken", "Chicken", "protein", "lb", 3, ["chicken breast", "chicken thigh", "chicken thighs"]),
    ("beef", "Beef", "protein", "lb", 3, ["ground beef", "steak", "stew meat"]),
    ("salmon", "Salmon", "protein", "lb", 2, ["salmon filet", "salmon fillet"]),
    ("tofu", "Tofu", "protein", "block", 7, ["firm tofu", "silken tofu"]),
    # Grains / starches
    ("rice", "Rice", "grain", "lb", 365, ["white rice", "brown rice", "jasmine rice", "basmati"]),
    ("pasta", "Pasta", "grain", "lb", 730, ["spaghetti", "penne", "rigatoni", "fusilli", "macaroni"]),
    ("bread", "Bread", "grain", "loaf", 7, ["sandwich bread", "sourdough", "baguette"]),
    ("flour", "Flour", "baking", "lb", 365, ["all-purpose flour", "ap flour", "bread flour"]),
    # Pantry / condiments
    ("olive oil", "Olive Oil", "oil", "bottle", 730, ["evoo", "extra virgin olive oil"]),
    ("soy sauce", "Soy Sauce", "condiment", "bottle", 1095, ["shoyu", "tamari"]),
    ("salt", "Salt", "spice", "container", None, ["kosher salt", "sea salt", "table salt"]),
    ("pepper", "Black Pepper", "spice", "container", None, ["black pepper", "ground pepper", "peppercorn"]),
    ("sugar", "Sugar", "baking", "lb", 730, ["granulated sugar", "white sugar"]),
    # Canned / dry
    ("canned tomatoes", "Canned Tomatoes", "pantry", "can", 730, ["diced tomatoes", "crushed tomatoes", "tomato sauce"]),
    ("black beans", "Black Beans", "pantry", "can", 1095, ["canned black beans"]),
    ("chickpeas", "Chickpeas", "pantry", "can", 1095, ["garbanzo beans", "canned chickpeas"]),
    ("lentils", "Lentils", "pantry", "lb", 730, ["red lentils", "green lentils", "brown lentils"]),
]


_NORMALIZE_RE = re.compile(r"[^a-z0-9 ]+")


def _normalize(name: str) -> str:
    return _NORMALIZE_RE.sub("", name.lower().strip())


def seed_starter_ingredients(db: Session) -> int:
    """Insert any starter ingredients that aren't already present. Returns count inserted."""
    existing_names = {
        row[0]
        for row in db.query(Ingredient.canonical_name).all()
    }
    inserted = 0
    for canonical, display, category, unit, shelf, aliases in STARTER_INGREDIENTS:
        if canonical in existing_names:
            continue
        db.add(
            Ingredient(
                canonical_name=canonical,
                display_name=display,
                category=category,
                default_unit=unit,
                typical_shelf_life_days=shelf,
                aliases=aliases,
            )
        )
        inserted += 1
    if inserted:
        db.commit()
    return inserted


def resolve_ingredient(db: Session, raw_name: str) -> uuid.UUID | None:
    """Resolve a raw item name to a canonical ingredient_id, or None.

    Match strategy (in order):
      1. Exact normalized match on canonical_name.
      2. Exact normalized match on any element of aliases.
      3. Substring: candidate canonical_name appears as a token in normalized raw_name.
    """
    normalized = _normalize(raw_name)
    if not normalized:
        return None

    # 1. Exact canonical match (case-insensitive)
    hit = (
        db.query(Ingredient.id)
        .filter(func.lower(Ingredient.canonical_name) == normalized)
        .first()
    )
    if hit:
        return hit[0]

    # 2. Alias match (Postgres array contains; case-insensitive via unnest)
    alias_hit = (
        db.query(Ingredient.id)
        .filter(Ingredient.aliases.any(normalized))
        .first()
    )
    if alias_hit:
        return alias_hit[0]

    # 3. Token-overlap fallback: pick the longest canonical_name that's a token in raw
    tokens = set(normalized.split())
    candidates = (
        db.query(Ingredient.id, Ingredient.canonical_name)
        .order_by(func.length(Ingredient.canonical_name).desc())
        .all()
    )
    for cid, cname in candidates:
        cname_norm = _normalize(cname)
        cname_tokens = set(cname_norm.split())
        if cname_norm in normalized or cname_tokens.issubset(tokens):
            return cid

    return None
