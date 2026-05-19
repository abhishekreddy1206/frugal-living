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
from app.models.food import (
    Ingredient,
    PantryItem,
    Recipe,
    ShoppingItem,
    ShoppingList,
)
from app.schemas.food import (
    CookedResponse,
    ExtractedItem,
    MealPlanRead,
    PantryCaptureRequest,
    PantryCaptureResponse,
    PantryItemRead,
    PlannedMealStatusResponse,
    PlannedMealStatusUpdate,
    PlannedMealWithRecipe,
    PurchasedItemRequest,
    PurchasedItemResponse,
    RecipeRead,
    SavingsRollup,
    ShoppingItemRead,
    ShoppingListRead,
    StretchConstraints,
    StretchResponse,
    WasteEventRead,
    WasteLogRequest,
    WeekPlanConstraints,
    WeekPlanResponse,
)
from app.services.events import emit_event
from app.services.ingredients import resolve_ingredient
from app.services.llm import (
    extract_pantry_from_image,
    generate_weekly_plan,
    stretch_recipes_for_pantry,
)
from app.services.meal_plans import (
    create_meal_plan_from_ai,
    get_planned_meal,
    load_active_plan,
    load_plan_recipes_map,
    mark_planned_meal_status,
)
from app.services.pantry import consume_for_recipe, snapshot_pantry
from app.services.recipes import create_recipe_from_ai, load_recipe_with_children
from app.services.shopping import (
    generate_from_meal_plan,
    load_active_list,
    mark_purchased,
)
from app.services.waste import log_waste, savings_rollup

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


def _serialize_plan(db: Session, plan) -> MealPlanRead:
    """Build a MealPlanRead with each PlannedMeal eagerly hydrated with its recipe."""
    recipes_map = load_plan_recipes_map(db, plan)
    meals = []
    for m in sorted(plan.meals, key=lambda x: (x.planned_date, x.meal_type)):
        recipe = recipes_map.get(m.recipe_id) if m.recipe_id else None
        meals.append(
            PlannedMealWithRecipe(
                id=m.id,
                recipe_id=m.recipe_id,
                planned_date=m.planned_date,
                meal_type=m.meal_type,
                servings=m.servings,
                status=m.status,
                notes=m.notes,
                recipe=RecipeRead.model_validate(recipe) if recipe else None,
            )
        )
    budget = float(plan.target_budget_usd) if plan.target_budget_usd is not None else None
    return MealPlanRead(
        id=plan.id,
        week_start=plan.week_start,
        name=plan.name,
        target_budget_usd=budget,
        status=plan.status,
        meals=meals,
    )


@router.post("/meal-plans/generate", response_model=WeekPlanResponse)
def generate_meal_plan(
    constraints: WeekPlanConstraints,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> WeekPlanResponse:
    """Generate a multi-constraint weekly meal plan via Opus 4.7."""
    pantry = snapshot_pantry(db, household)
    ai_plan = generate_weekly_plan(pantry, constraints)
    plan = create_meal_plan_from_ai(
        db,
        household=household,
        user=user,
        ai_plan=ai_plan,
        constraints=constraints,
    )
    db.commit()
    db.refresh(plan)

    return WeekPlanResponse(
        plan=_serialize_plan(db, plan),
        pantry_coverage_summary=ai_plan.pantry_coverage_summary,
        total_estimated_cost_usd=ai_plan.total_estimated_cost_usd,
    )


@router.get("/meal-plans/active", response_model=MealPlanRead | None)
def get_active_meal_plan(
    household: CurrentHousehold,
    db: Annotated[Session, Depends(get_db)],
) -> MealPlanRead | None:
    plan = load_active_plan(db, household)
    if plan is None:
        return None
    return _serialize_plan(db, plan)


@router.post(
    "/planned-meals/{planned_meal_id}/status",
    response_model=PlannedMealStatusResponse,
)
def update_planned_meal_status(
    planned_meal_id: uuid.UUID,
    update: PlannedMealStatusUpdate,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> PlannedMealStatusResponse:
    """Transition a planned meal. cooked → consumes pantry + emits food.meal.cooked.
    skipped → emits food.meal.skipped. Other statuses just update the field."""
    pm = get_planned_meal(db, planned_meal_id)
    if pm is None or pm.meal_plan.household_id != household.id:
        raise HTTPException(404, "planned meal not found")

    prev_status = pm.status
    mark_planned_meal_status(pm, update.status)

    response = PlannedMealStatusResponse(
        planned_meal_id=pm.id,
        new_status=update.status,
    )

    if update.status == "cooked" and prev_status != "cooked":
        recipe = (
            db.query(Recipe)
            .options(selectinload(Recipe.ingredients))
            .filter(Recipe.id == pm.recipe_id, Recipe.deleted_at.is_(None))
            .one_or_none()
        )
        if recipe is None:
            raise HTTPException(409, "planned meal references missing recipe")
        servings = update.servings_cooked or pm.servings
        result = consume_for_recipe(
            db, household=household, recipe=recipe, servings_cooked=servings
        )
        emit_event(
            db,
            event_type="food.meal.cooked",
            household_id=household.id,
            user_id=user.id,
            entity_type="planned_meal",
            entity_id=pm.id,
            payload={
                "recipe_id": str(recipe.id),
                "recipe_name": recipe.name,
                "servings": servings,
                "cooked_from_pantry_pct": result.cooked_from_pantry_pct,
                "estimated_value_usd": result.estimated_value_usd,
                "planned_meal_id": str(pm.id),
            },
        )
        response.cooked_from_pantry_pct = result.cooked_from_pantry_pct
        response.estimated_value_usd = result.estimated_value_usd
        response.decremented_item_ids = result.decremented_item_ids
    elif update.status == "skipped" and prev_status != "skipped":
        emit_event(
            db,
            event_type="food.meal.skipped",
            household_id=household.id,
            user_id=user.id,
            entity_type="planned_meal",
            entity_id=pm.id,
            payload={"planned_meal_id": str(pm.id), "recipe_id": str(pm.recipe_id)},
        )

    db.commit()
    return response


# ---------- Shopping (Sprint 4) ----------


def _serialize_shopping_list(sl: ShoppingList, items: list[ShoppingItem]) -> ShoppingListRead:
    return ShoppingListRead(
        id=sl.id,
        meal_plan_id=sl.meal_plan_id,
        name=sl.name,
        status=sl.status,
        target_date=sl.target_date,
        items=[ShoppingItemRead.model_validate(i) for i in items],
    )


@router.post("/shopping-lists/from-plan", response_model=ShoppingListRead)
def shopping_list_from_plan(
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ShoppingListRead:
    """Aggregate the active meal plan's ingredients into a shopping list,
    subtracting what's already in the pantry."""
    plan = load_active_plan(db, household)
    if plan is None:
        raise HTTPException(409, "no active meal plan to derive shopping list from")
    sl = generate_from_meal_plan(db, household=household, user=user, meal_plan=plan)
    db.commit()
    items = (
        db.query(ShoppingItem)
        .filter(ShoppingItem.shopping_list_id == sl.id)
        .order_by(ShoppingItem.raw_name)
        .all()
    )
    return _serialize_shopping_list(sl, items)


@router.get("/shopping-lists/active", response_model=ShoppingListRead | None)
def get_active_shopping_list(
    household: CurrentHousehold,
    db: Annotated[Session, Depends(get_db)],
) -> ShoppingListRead | None:
    sl = load_active_list(db, household)
    if sl is None:
        return None
    items = (
        db.query(ShoppingItem)
        .filter(ShoppingItem.shopping_list_id == sl.id)
        .order_by(ShoppingItem.status, ShoppingItem.raw_name)
        .all()
    )
    return _serialize_shopping_list(sl, items)


@router.post(
    "/shopping-items/{item_id}/purchased",
    response_model=PurchasedItemResponse,
)
def mark_shopping_item_purchased(
    item_id: uuid.UUID,
    request: PurchasedItemRequest,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> PurchasedItemResponse:
    """Mark a shopping item purchased: copy into the pantry, emit event."""
    item = db.get(ShoppingItem, item_id)
    if item is None:
        raise HTTPException(404, "shopping item not found")
    # Verify household ownership via parent list
    sl = db.get(ShoppingList, item.shopping_list_id)
    if sl is None or sl.household_id != household.id:
        raise HTTPException(404, "shopping item not found")
    if item.status == "purchased":
        # Idempotent: don't double-add to pantry
        return PurchasedItemResponse(
            shopping_item_id=item.id,
            pantry_item_id=uuid.UUID(int=0),
            status="already_purchased",
        )

    pantry_item = mark_purchased(
        db,
        household=household,
        user=user,
        item=item,
        actual_price_usd=request.actual_price_usd,
        location_id=request.location_id,
    )
    db.commit()
    return PurchasedItemResponse(
        shopping_item_id=item.id,
        pantry_item_id=pantry_item.id,
        status="purchased",
    )


# ---------- Preservation ----------


@router.get("/preservation/methods")
def preservation_methods():
    return {"methods": [], "todo": "Seed from USDA-aligned catalog"}


# ---------- Waste (Sprint 5) ----------


@router.post("/waste", response_model=WasteEventRead)
def post_waste(
    request: WasteLogRequest,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> WasteEventRead:
    """Log a food waste event. If linked to a pantry item, decrement/delete it."""
    event = log_waste(db, household=household, user_id=user.id, request=request)
    db.commit()
    return WasteEventRead.model_validate(event)


@router.get("/waste/savings", response_model=SavingsRollup)
def waste_savings(
    household: CurrentHousehold,
    db: Annotated[Session, Depends(get_db)],
    period_days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> SavingsRollup:
    return savings_rollup(db, household=household, period_days=period_days)
