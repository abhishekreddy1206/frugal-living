"""Tests for app.services.recipes (recipe persistence)."""
from __future__ import annotations

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.core import Event, Household, User
from app.models.food import Recipe, RecipeIngredient, RecipeStep
from app.schemas.food import AIRecipe, AIRecipeIngredient, AIRecipeStep
from app.services.recipes import (
    _slugify,
    create_recipe_from_ai,
    load_recipe_with_children,
)


def test_slugify_handles_name_with_punctuation():
    s = _slugify("Tomato & Basil Pasta!")
    assert s.startswith("tomato-basil-pasta-")
    assert len(s.split("-")[-1]) == 6  # 6-char suffix


def test_slugify_unique_per_call():
    s1 = _slugify("X")
    s2 = _slugify("X")
    assert s1 != s2


def test_create_recipe_from_ai_persists_full_tree(db):
    household = db.get(Household, DEV_HOUSEHOLD_ID)
    user = db.get(User, DEV_USER_ID)

    ai = AIRecipe(
        name="Garlic Spaghetti",
        description="A staple weeknight dinner.",
        servings=4,
        prep_time_min=5,
        cook_time_min=15,
        cuisine="Italian",
        difficulty="easy",
        tags=["quick", "vegetarian"],
        estimated_cost_usd=2.5,
        estimated_cost_per_serving_usd=0.625,
        ingredients=[
            AIRecipeIngredient(
                raw_name="spaghetti", quantity=1, unit="lb",
                substitutions=["any long pasta"],
            ),
            AIRecipeIngredient(
                raw_name="garlic", quantity=4, unit="clove",
            ),
            AIRecipeIngredient(
                raw_name="dragonfruit", quantity=1, unit="each",  # unresolvable
            ),
        ],
        steps=[
            AIRecipeStep(content="Boil pasta.", duration_seconds=600),
            AIRecipeStep(content="Sauté garlic."),
        ],
        pantry_items_used=["spaghetti", "garlic"],
    )

    recipe = create_recipe_from_ai(db, household=household, user=user, ai_recipe=ai)
    db.flush()

    persisted = db.get(Recipe, recipe.id)
    assert persisted is not None
    assert persisted.name == "Garlic Spaghetti"
    assert persisted.is_ai_generated is True
    assert persisted.cuisine == "Italian"
    assert persisted.created_by_user_id == DEV_USER_ID
    assert persisted.metadata_["pantry_items_used"] == ["spaghetti", "garlic"]

    ingredients = (
        db.query(RecipeIngredient).filter_by(recipe_id=recipe.id).all()
    )
    assert len(ingredients) == 3
    spaghetti = next(i for i in ingredients if i.raw_name == "spaghetti")
    assert spaghetti.ingredient_id is not None  # resolves to "pasta" canonical
    assert spaghetti.substitutions == ["any long pasta"]
    dragonfruit = next(i for i in ingredients if i.raw_name == "dragonfruit")
    assert dragonfruit.ingredient_id is None  # unresolved is OK

    steps = (
        db.query(RecipeStep)
        .filter_by(recipe_id=recipe.id)
        .order_by(RecipeStep.order_index)
        .all()
    )
    assert len(steps) == 2
    assert steps[0].content == "Boil pasta."
    assert steps[0].order_index == 0
    assert steps[1].order_index == 1

    events = (
        db.query(Event)
        .filter(Event.event_type == "food.recipe.generated", Event.entity_id == recipe.id)
        .all()
    )
    assert len(events) == 1
    assert events[0].payload["pantry_items_used_count"] == 2


def test_load_recipe_with_children_eagerly_loads(db):
    household = db.get(Household, DEV_HOUSEHOLD_ID)
    ai = AIRecipe(
        name="Test Soup",
        servings=2,
        difficulty="easy",
        ingredients=[AIRecipeIngredient(raw_name="rice", quantity=0.5, unit="cup")],
        steps=[AIRecipeStep(content="Boil.")],
    )
    recipe = create_recipe_from_ai(db, household=household, user=None, ai_recipe=ai)
    db.flush()

    loaded = load_recipe_with_children(db, recipe.id)
    assert loaded is not None
    assert len(loaded.ingredients) == 1
    assert len(loaded.steps) == 1
