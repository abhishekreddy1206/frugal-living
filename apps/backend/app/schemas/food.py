"""Pydantic request/response schemas for the food tier."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

# ---------- Pantry capture ----------

class PantryCaptureRequest(BaseModel):
    """Photo-to-pantry input. Image arrives as base64 (not persisted in v1)."""

    image_base64: str = Field(..., min_length=32, description="Base64-encoded image data")
    media_type: str = Field(default="image/jpeg", pattern=r"^image/(jpeg|jpg|png|webp|heic)$")
    location_id: uuid.UUID | None = Field(
        default=None, description="Which pantry location these items belong to"
    )


class ExtractedItem(BaseModel):
    """A single item the vision model extracted from a photo, pre-persistence."""

    raw_name: str = Field(..., min_length=1, max_length=200)
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=32)
    confidence: float = Field(..., ge=0.0, le=1.0)
    suggested_expires_at: date | None = None
    notes: str | None = Field(default=None, max_length=500)


class ExtractedPantry(BaseModel):
    """Full structured response from extract_pantry_from_image."""

    items: list[ExtractedItem]


class PantryItemRead(BaseModel):
    """Persisted pantry item, returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    raw_name: str
    ingredient_id: uuid.UUID | None
    location_id: uuid.UUID | None
    quantity: float | None
    unit: str | None
    purchased_at: date | None
    opened_at: date | None
    expires_at: date | None
    estimated_value: float | None
    source: str
    confidence: float | None
    photo_url: str | None
    notes: str | None
    created_at: datetime


class PantryCaptureResponse(BaseModel):
    items: list[PantryItemRead]
    created_count: int


# ---------- Recipe stretcher (Sprint 2) ----------


class PantrySnapshotItem(BaseModel):
    """Compact form of a pantry item passed to the LLM."""

    raw_name: str
    quantity: float | None
    unit: str | None
    expires_in_days: int | None  # negative means already expired
    ingredient_id: uuid.UUID | None


class StretchConstraints(BaseModel):
    """Optional user-supplied filters."""

    max_prep_min: int | None = Field(default=None, ge=0, le=240)
    max_cook_min: int | None = Field(default=None, ge=0, le=480)
    prioritize_expiring: bool = True
    count: int = Field(default=5, ge=1, le=10)
    cuisines: list[str] | None = None
    meal_type: str | None = Field(default=None, pattern=r"^(breakfast|lunch|dinner|snack|any)$")


class AIRecipeIngredient(BaseModel):
    raw_name: str = Field(..., min_length=1, max_length=200)
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=32)
    is_optional: bool = False
    substitutions: list[str] = Field(default_factory=list)


class AIRecipeStep(BaseModel):
    content: str = Field(..., min_length=1)
    duration_seconds: int | None = Field(default=None, ge=0, le=86400)


class AIRecipe(BaseModel):
    """A single Claude-suggested recipe."""

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    servings: int = Field(default=4, ge=1, le=24)
    prep_time_min: int | None = Field(default=None, ge=0)
    cook_time_min: int | None = Field(default=None, ge=0)
    cuisine: str | None = Field(default=None, max_length=64)
    difficulty: str = Field(default="medium", pattern=r"^(easy|medium|hard)$")
    tags: list[str] = Field(default_factory=list)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    estimated_cost_per_serving_usd: float | None = Field(default=None, ge=0)
    ingredients: list[AIRecipeIngredient]
    steps: list[AIRecipeStep]
    pantry_items_used: list[str] = Field(
        default_factory=list,
        description="Raw names from the pantry snapshot that this recipe uses",
    )


class StretchSuggestions(BaseModel):
    """Full structured response from stretch_recipes_for_pantry."""

    recipes: list[AIRecipe]


class RecipeIngredientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    raw_name: str
    ingredient_id: uuid.UUID | None
    quantity: float | None
    unit: str | None
    is_optional: bool
    substitutions: list[str]


class RecipeStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_index: int
    content: str
    duration_seconds: int | None


class RecipeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    servings: int
    prep_time_min: int | None
    cook_time_min: int | None
    cuisine: str | None
    difficulty: str
    tags: list[str]
    estimated_cost_usd: float | None
    estimated_cost_per_serving_usd: float | None
    is_ai_generated: bool
    ingredients: list[RecipeIngredientRead]
    steps: list[RecipeStepRead]


class StretchResponse(BaseModel):
    recipes: list[RecipeRead]
    pantry_size: int


class CookedResponse(BaseModel):
    recipe_id: uuid.UUID
    recipe_name: str
    servings: int
    cooked_from_pantry_pct: float
    decremented_item_ids: list[uuid.UUID]
    estimated_value_usd: float | None


# ---------- Weekly meal plan (Sprint 3) ----------


class WeekPlanConstraints(BaseModel):
    """User-supplied parameters for a weekly plan generation."""

    week_start: date
    target_budget_usd: float | None = Field(default=None, ge=0)
    dinners_per_week: int = Field(default=7, ge=1, le=7)
    max_cost_per_serving_usd: float | None = Field(default=None, ge=0)
    dietary_constraints: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=500)


class AIPlannedMeal(BaseModel):
    """One slot in the AI-generated week."""

    planned_date: date
    meal_type: str = Field(default="dinner", pattern=r"^(breakfast|lunch|dinner|snack)$")
    recipe: AIRecipe
    rationale: str | None = Field(
        default=None,
        description="Why this slot picks this recipe — usually mentions pantry items used",
    )


class AIWeekPlan(BaseModel):
    """Full structured response from generate_weekly_plan."""

    meals: list[AIPlannedMeal]
    total_estimated_cost_usd: float | None = None
    pantry_coverage_summary: str | None = None


class PlannedMealRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    recipe_id: uuid.UUID | None
    planned_date: date
    meal_type: str
    servings: int
    status: str  # planned | prepped | cooked | skipped
    notes: str | None


class PlannedMealWithRecipe(PlannedMealRead):
    """Eagerly-loaded planned meal + its recipe payload."""

    recipe: RecipeRead | None = None


class MealPlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    week_start: date
    name: str | None
    target_budget_usd: float | None
    status: str  # draft | active | archived
    meals: list[PlannedMealWithRecipe]


class WeekPlanResponse(BaseModel):
    plan: MealPlanRead
    pantry_coverage_summary: str | None
    total_estimated_cost_usd: float | None


class PlannedMealStatusUpdate(BaseModel):
    status: str = Field(..., pattern=r"^(planned|prepped|cooked|skipped)$")
    servings_cooked: int | None = Field(default=None, ge=1, le=24)


class PlannedMealStatusResponse(BaseModel):
    planned_meal_id: uuid.UUID
    new_status: str
    cooked_from_pantry_pct: float | None = None
    estimated_value_usd: float | None = None
    decremented_item_ids: list[uuid.UUID] = Field(default_factory=list)


# ---------- Shopping list (Sprint 4) ----------


class ShoppingItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ingredient_id: uuid.UUID | None
    raw_name: str
    quantity: float | None
    unit: str | None
    store: str | None
    estimated_price_usd: float | None
    actual_price_usd: float | None
    status: str  # pending | purchased | skipped


class ShoppingListRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    meal_plan_id: uuid.UUID | None
    name: str | None
    status: str  # active | completed | archived
    target_date: date | None
    items: list[ShoppingItemRead] = Field(default_factory=list)


class PurchasedItemRequest(BaseModel):
    actual_price_usd: float | None = Field(default=None, ge=0)
    location_id: uuid.UUID | None = None


class PurchasedItemResponse(BaseModel):
    shopping_item_id: uuid.UUID
    pantry_item_id: uuid.UUID
    status: str


# ---------- Food waste (Sprint 5) ----------


class WasteLogRequest(BaseModel):
    pantry_item_id: uuid.UUID | None = None
    ingredient_name: str = Field(..., min_length=1, max_length=200)
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=32)
    reason: str | None = Field(
        default=None,
        pattern=r"^(spoiled|forgotten|over_cooked|over_purchased|other)$",
    )
    estimated_value_usd: float | None = Field(default=None, ge=0)
    occurred_on: date | None = None


class WasteEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pantry_item_id: uuid.UUID | None
    ingredient_name: str
    quantity: float | None
    unit: str | None
    reason: str | None
    estimated_value_usd: float | None
    occurred_on: date


class SavingsRollup(BaseModel):
    period_days: int
    cooked_from_pantry_value_usd: float
    waste_value_usd: float
    net_savings_usd: float
    cooked_meals_count: int
    waste_events_count: int
    expiring_soon: list[PantryItemRead] = Field(default_factory=list)


# ---------- Preservation (Sprint 6) ----------


PRESERVATION_METHODS = [
    "canning_water_bath",
    "canning_pressure",
    "freezing",
    "dehydrating",
    "fermenting",
    "pickling",
    "curing",
]
_PRESERVATION_METHOD_PATTERN = "^(" + "|".join(PRESERVATION_METHODS) + ")$"


class PreservationMethodInfo(BaseModel):
    method: str
    label: str
    safe_for: list[str]  # high-acid | low-acid | dairy | meat | universal
    typical_shelf_life_days: int
    safety_notes: str


class PreservationAdviceRequest(BaseModel):
    method: str = Field(..., pattern=_PRESERVATION_METHOD_PATTERN)
    ingredient_name: str = Field(..., min_length=1, max_length=200)
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=32)


class PreservationAdvice(BaseModel):
    """Structured guidance returned by Claude. May refuse on safety grounds."""

    is_safe: bool
    refusal_reason: str | None = Field(
        default=None,
        description="If is_safe=False, why we refuse (e.g. low-acid water bath)",
    )
    recommended_method: str | None = None
    safety_warnings: list[str] = Field(default_factory=list)
    usda_references: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    expected_shelf_life_days: int | None = None
    equipment: list[str] = Field(default_factory=list)


class PreservationJobCreate(BaseModel):
    method: str = Field(..., pattern=_PRESERVATION_METHOD_PATTERN)
    ingredient_name: str = Field(..., min_length=1, max_length=200)
    quantity_in: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=32)
    source_pantry_item_id: uuid.UUID | None = None
    safety_check_passed: bool = False
    notes: str | None = None


class PreservationJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    method: str
    ingredient_name: str
    quantity_in: float | None
    quantity_out: float | None
    unit: str | None
    started_at: datetime | None
    completed_at: datetime | None
    expires_at: date | None
    safety_check_passed: bool
    safety_notes: str | None
    notes: str | None


class PreservationJobComplete(BaseModel):
    quantity_out: float | None = Field(default=None, ge=0)
    expires_at: date | None = None
    safety_notes: str | None = None
