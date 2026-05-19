"""Tier A — food routes."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, nulls_last
from sqlalchemy.orm import Session, selectinload

from app.auth import CurrentHousehold, CurrentUser
from app.db import get_db
from app.models.food import Ingredient, PantryItem, Recipe
from app.schemas.food import (
    CookedResponse,
    ExtractedItem,
    PantryCaptureRequest,
    PantryCaptureResponse,
    PantryItemRead,
    RecipeRead,
    StretchConstraints,
    StretchResponse,
)
from app.services.events import emit_event
from app.services.ingredients import resolve_ingredient
from app.services.llm import extract_pantry_from_image, stretch_recipes_for_pantry
from app.services.pantry import consume_for_recipe, snapshot_pantry
from app.services.recipes import create_recipe_from_ai, load_recipe_with_children

router = APIRouter()


# ---------- Pantry ----------


@router.get("/pantry", response_model=list[PantryItemRead])
def list_pantry(
    household: CurrentHousehold,
    db: Annotated[Session, Depends(get_db)],
) -> list[PantryItem]:
    """List the current household's pantry, soonest expiry first."""
    return (
        db.query(PantryItem)
        .filter(
            PantryItem.household_id == household.id,
            PantryItem.deleted_at.is_(None),
        )
        .order_by(nulls_last(asc(PantryItem.expires_at)), PantryItem.created_at.desc())
        .all()
    )


def _suggest_expiry(item: ExtractedItem, ingredient: Ingredient | None) -> date | None:
    """If the LLM didn't suggest an expiry but we know the typical shelf life, project it."""
    if item.suggested_expires_at is not None:
        return item.suggested_expires_at
    if ingredient and ingredient.typical_shelf_life_days:
        return date.today() + timedelta(days=ingredient.typical_shelf_life_days)
    return None


@router.post("/pantry/capture", response_model=PantryCaptureResponse)
def capture_pantry(
    request: PantryCaptureRequest,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> PantryCaptureResponse:
    """Photo → pantry items. Sonnet 4.6 vision extracts; we resolve + persist + emit events."""
    extracted = extract_pantry_from_image(request.image_base64, request.media_type)

    def _f(v):  # Numeric -> JSON-safe float or None
        return float(v) if v is not None else None

    created: list[PantryItem] = []
    for item in extracted.items:
        ingredient_id = resolve_ingredient(db, item.raw_name)
        ingredient = db.get(Ingredient, ingredient_id) if ingredient_id else None
        unit = item.unit or (ingredient.default_unit if ingredient else None)

        pantry_item = PantryItem(
            household_id=household.id,
            location_id=request.location_id,
            ingredient_id=ingredient_id,
            raw_name=item.raw_name,
            quantity=item.quantity,
            unit=unit,
            expires_at=_suggest_expiry(item, ingredient),
            source="photo_capture",
            confidence=item.confidence,
            notes=item.notes,
        )
        db.add(pantry_item)
        db.flush()

        emit_event(
            db,
            event_type="food.pantry_item.added",
            household_id=household.id,
            user_id=user.id,
            entity_type="pantry_item",
            entity_id=pantry_item.id,
            payload={
                "raw_name": pantry_item.raw_name,
                "quantity": _f(pantry_item.quantity),
                "unit": pantry_item.unit,
                "ingredient_id": str(ingredient_id) if ingredient_id else None,
                "source": "photo_capture",
                "confidence": _f(pantry_item.confidence),
            },
        )
        created.append(pantry_item)

    db.commit()
    for p in created:
        db.refresh(p)

    return PantryCaptureResponse(
        items=[PantryItemRead.model_validate(p) for p in created],
        created_count=len(created),
    )


@router.post("/pantry/receipt")
def capture_receipt(db: Annotated[Session, Depends(get_db)]):
    """Receipt-to-pantry. Stub — Sprint 1.5."""
    return {"receipt": None, "items": [], "todo": "Wire to services.llm.extract_receipt"}


@router.post("/pantry/barcode")
def capture_barcode(db: Annotated[Session, Depends(get_db)]):
    """Barcode scan. Stub — Sprint 1.5."""
    return {"item": None, "todo": "Wire to Open Food Facts lookup"}


# ---------- Recipes (Sprint 2) ----------


@router.get("/recipes/stretch", response_model=StretchResponse)
def stretch_recipes(
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    max_prep_min: Annotated[int | None, Query(ge=0, le=240)] = None,
    max_cook_min: Annotated[int | None, Query(ge=0, le=480)] = None,
    prioritize_expiring: bool = True,
    count: Annotated[int, Query(ge=1, le=10)] = 5,
    cuisines: Annotated[list[str] | None, Query()] = None,
    meal_type: Annotated[
        str | None, Query(pattern=r"^(breakfast|lunch|dinner|snack|any)$")
    ] = None,
) -> StretchResponse:
    """Suggest recipes that maximize what's already in the household's pantry."""
    pantry = snapshot_pantry(db, household)
    constraints = StretchConstraints(
        max_prep_min=max_prep_min,
        max_cook_min=max_cook_min,
        prioritize_expiring=prioritize_expiring,
        count=count,
        cuisines=cuisines,
        meal_type=meal_type,
    )
    suggestions = stretch_recipes_for_pantry(pantry, constraints)

    persisted: list[Recipe] = []
    for ai_recipe in suggestions.recipes:
        recipe = create_recipe_from_ai(
            db, household=household, user=user, ai_recipe=ai_recipe
        )
        persisted.append(recipe)
    db.commit()

    # Reload with children eagerly for serialization
    out = []
    for r in persisted:
        loaded = load_recipe_with_children(db, r.id)
        if loaded is not None:
            out.append(RecipeRead.model_validate(loaded))

    return StretchResponse(recipes=out, pantry_size=len(pantry))


@router.post("/recipes/{recipe_id}/cooked", response_model=CookedResponse)
def mark_recipe_cooked(
    recipe_id: uuid.UUID,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    servings_cooked: Annotated[int | None, Query(ge=1, le=24)] = None,
) -> CookedResponse:
    """Mark a recipe as cooked: decrement pantry + emit food.meal.cooked."""
    recipe = (
        db.query(Recipe)
        .options(selectinload(Recipe.ingredients))
        .filter(Recipe.id == recipe_id, Recipe.deleted_at.is_(None))
        .one_or_none()
    )
    if recipe is None:
        raise HTTPException(404, "recipe not found")

    cooked_servings = servings_cooked if servings_cooked is not None else recipe.servings
    result = consume_for_recipe(
        db, household=household, recipe=recipe, servings_cooked=cooked_servings
    )

    emit_event(
        db,
        event_type="food.meal.cooked",
        household_id=household.id,
        user_id=user.id,
        entity_type="recipe",
        entity_id=recipe.id,
        payload={
            "recipe_id": str(recipe.id),
            "recipe_name": recipe.name,
            "servings": cooked_servings,
            "cooked_from_pantry_pct": result.cooked_from_pantry_pct,
            "estimated_value_usd": result.estimated_value_usd,
        },
    )
    db.commit()

    return CookedResponse(
        recipe_id=recipe.id,
        recipe_name=recipe.name,
        servings=cooked_servings,
        cooked_from_pantry_pct=result.cooked_from_pantry_pct,
        decremented_item_ids=result.decremented_item_ids,
        estimated_value_usd=result.estimated_value_usd,
    )


# ---------- Meal planning (Sprint 3) ----------


@router.post("/meal-plans/generate")
def generate_meal_plan(db: Annotated[Session, Depends(get_db)]):
    return {"meal_plan": None, "todo": "Wire to services.llm.generate_weekly_plan"}


# ---------- Shopping ----------


@router.get("/shopping-list")
def get_shopping_list(db: Annotated[Session, Depends(get_db)]):
    return {"items": [], "todo": "Derive from active meal plan minus pantry"}


# ---------- Preservation ----------


@router.get("/preservation/methods")
def preservation_methods():
    return {"methods": [], "todo": "Seed from USDA-aligned catalog"}


# ---------- Waste ----------


@router.post("/waste")
def log_waste(db: Annotated[Session, Depends(get_db)]):
    return {"event": None, "todo": "Wire to FoodWasteEvent + emit savings/streak update"}
