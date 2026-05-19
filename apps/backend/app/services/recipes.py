"""
Recipe persistence helpers — turn AI-suggested recipes into real food.recipes rows.

AI-generated recipes are persisted so that:
  * the user can later mark one as cooked (which decrements pantry + emits an event)
  * stretches and meal-plans can reuse and refine prior suggestions
  * we can show "you've cooked this before" affordances
"""
from __future__ import annotations

import re
import uuid

from sqlalchemy.orm import Session, selectinload

from app.models.core import Household, User
from app.models.food import Recipe, RecipeIngredient, RecipeStep
from app.schemas.food import AIRecipe
from app.services.events import emit_event
from app.services.ingredients import resolve_ingredient

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    """Lowercase, replace non-alphanumeric with hyphens, trim, append 6-hex suffix.

    Suffix guarantees uniqueness without a DB roundtrip — recipe slugs are
    user-facing but not hand-typed, so the suffix is fine.
    """
    base = _SLUG_RE.sub("-", name.lower()).strip("-")[:200]
    suffix = uuid.uuid4().hex[:6]
    return f"{base or 'recipe'}-{suffix}"


def create_recipe_from_ai(
    db: Session,
    *,
    household: Household,
    user: User | None,
    ai_recipe: AIRecipe,
) -> Recipe:
    """Persist an AIRecipe as a full Recipe + ingredients + steps. Emits food.recipe.generated."""
    recipe = Recipe(
        name=ai_recipe.name,
        slug=_slugify(ai_recipe.name),
        description=ai_recipe.description,
        servings=ai_recipe.servings,
        prep_time_min=ai_recipe.prep_time_min,
        cook_time_min=ai_recipe.cook_time_min,
        cuisine=ai_recipe.cuisine,
        difficulty=ai_recipe.difficulty,
        tags=list(ai_recipe.tags),
        estimated_cost_usd=ai_recipe.estimated_cost_usd,
        estimated_cost_per_serving_usd=ai_recipe.estimated_cost_per_serving_usd,
        is_user_created=False,
        created_by_user_id=user.id if user else None,
        is_ai_generated=True,
        metadata_={"pantry_items_used": list(ai_recipe.pantry_items_used)},
    )
    db.add(recipe)
    db.flush()

    for ing in ai_recipe.ingredients:
        db.add(
            RecipeIngredient(
                recipe_id=recipe.id,
                ingredient_id=resolve_ingredient(db, ing.raw_name),
                raw_name=ing.raw_name,
                quantity=ing.quantity,
                unit=ing.unit,
                is_optional=ing.is_optional,
                substitutions=list(ing.substitutions),
                order_index=0,
            )
        )

    for idx, step in enumerate(ai_recipe.steps):
        db.add(
            RecipeStep(
                recipe_id=recipe.id,
                order_index=idx,
                content=step.content,
                duration_seconds=step.duration_seconds,
            )
        )

    db.flush()

    emit_event(
        db,
        event_type="food.recipe.generated",
        household_id=household.id,
        user_id=user.id if user else None,
        entity_type="recipe",
        entity_id=recipe.id,
        payload={
            "recipe_name": recipe.name,
            "cuisine": recipe.cuisine,
            "pantry_items_used_count": len(ai_recipe.pantry_items_used),
            "estimated_cost_per_serving_usd": float(recipe.estimated_cost_per_serving_usd)
            if recipe.estimated_cost_per_serving_usd is not None
            else None,
        },
    )
    return recipe


def load_recipe_with_children(db: Session, recipe_id: uuid.UUID) -> Recipe | None:
    """Eagerly load a recipe with ingredients + steps for response serialization."""
    return (
        db.query(Recipe)
        .options(
            selectinload(Recipe.ingredients),
            selectinload(Recipe.steps),
        )
        .filter(Recipe.id == recipe_id, Recipe.deleted_at.is_(None))
        .one_or_none()
    )
