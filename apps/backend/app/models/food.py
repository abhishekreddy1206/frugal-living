"""
Food tier — pantry, recipes, meal planning, preservation, food waste, shopping.
This is Tier A. All tables live in the `food` schema.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.core import TimestampMixin

# ---------- Canonical ingredient catalog ----------

class Ingredient(Base, TimestampMixin):
    """Canonical ingredient table. Shared across recipes, pantry, shopping lists."""
    __tablename__ = "ingredients"
    __table_args__ = (
        Index("idx_ingredients_canonical", "canonical_name"),
        {"schema": "food"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_name: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # protein, grain, dairy, produce, condiment, spice, oil, baking, beverage, frozen, other
    default_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    typical_shelf_life_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


# ---------- Pantry (Priority 1) ----------

class PantryLocation(Base, TimestampMixin):
    """Where things are stored — main pantry, fridge, freezer, root cellar, etc."""
    __tablename__ = "pantry_locations"
    __table_args__ = {"schema": "food"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    location_type: Mapped[str] = mapped_column(String(32), default="pantry", nullable=False)
    # pantry | fridge | freezer | root_cellar | spice_rack | other
    temperature_c: Mapped[float | None] = mapped_column(Numeric(4, 1), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class PantryItem(Base, TimestampMixin):
    """A unit of food currently in the household. Captured via photo, receipt, or manual."""
    __tablename__ = "pantry_items"
    __table_args__ = (
        Index("idx_pantry_household_expires", "household_id", "expires_at"),
        Index("idx_pantry_ingredient", "ingredient_id"),
        {"schema": "food"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.pantry_locations.id"), nullable=True
    )
    ingredient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.ingredients.id"), nullable=True
    )
    raw_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # raw text as captured, before canonical resolution

    quantity: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    purchased_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    opened_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    estimated_value: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    # manual | photo_capture | receipt_scan | barcode | imported
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    # 0..1 — for AI-captured items
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


# ---------- Receipts (receipt-scan capture path) ----------

class Receipt(Base, TimestampMixin):
    """A grocery receipt captured via photo. Parses into pantry_items + spend tracking."""
    __tablename__ = "receipts"
    __table_args__ = (
        Index("idx_receipts_household_date", "household_id", "purchased_at"),
        {"schema": "food"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False
    )
    store_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    purchased_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    subtotal_usd: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    tax_usd: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    total_usd: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    parse_status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    # pending | parsed | failed | confirmed
    parse_confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    raw_ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


# ---------- Recipes (Priority 2: Recipe Stretcher) ----------

class Recipe(Base, TimestampMixin):
    __tablename__ = "recipes"
    __table_args__ = {"schema": "food"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(220), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_attribution: Mapped[str | None] = mapped_column(String(200), nullable=True)
    servings: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    prep_time_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cook_time_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cuisine: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    difficulty: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    estimated_cost_per_serving_usd: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    is_user_created: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=True
    )
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # If this recipe was imported from a content source (blog, YouTube), link it.
    imported_from_content_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    ingredients: Mapped[list[RecipeIngredient]] = relationship(back_populates="recipe", cascade="all, delete-orphan")
    steps: Mapped[list[RecipeStep]] = relationship(back_populates="recipe", cascade="all, delete-orphan")


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"
    __table_args__ = {"schema": "food"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.recipes.id", ondelete="CASCADE"), nullable=False
    )
    ingredient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.ingredients.id"), nullable=True
    )
    raw_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    substitutions: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    recipe: Mapped[Recipe] = relationship(back_populates="ingredients")


class RecipeStep(Base):
    __tablename__ = "recipe_steps"
    __table_args__ = {"schema": "food"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.recipes.id", ondelete="CASCADE"), nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    recipe: Mapped[Recipe] = relationship(back_populates="steps")


# ---------- Meal planning (Priority 3) ----------

class MealPlan(Base, TimestampMixin):
    __tablename__ = "meal_plans"
    __table_args__ = {"schema": "food"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False, index=True
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    target_budget_usd: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)
    # draft | active | archived
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    meals: Mapped[list[PlannedMeal]] = relationship(back_populates="meal_plan", cascade="all, delete-orphan")


class PlannedMeal(Base, TimestampMixin):
    __tablename__ = "planned_meals"
    __table_args__ = {"schema": "food"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meal_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.meal_plans.id", ondelete="CASCADE"), nullable=False
    )
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.recipes.id"), nullable=True
    )
    planned_date: Mapped[date] = mapped_column(Date, nullable=False)
    meal_type: Mapped[str] = mapped_column(String(16), default="dinner", nullable=False)
    # breakfast | lunch | dinner | snack
    servings: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="planned", nullable=False)
    # planned | prepped | cooked | skipped
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    meal_plan: Mapped[MealPlan] = relationship(back_populates="meals")


# ---------- Shopping ----------

class ShoppingList(Base, TimestampMixin):
    __tablename__ = "shopping_lists"
    __table_args__ = {"schema": "food"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False, index=True
    )
    meal_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.meal_plans.id"), nullable=True
    )
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class ShoppingItem(Base, TimestampMixin):
    __tablename__ = "shopping_items"
    __table_args__ = {"schema": "food"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shopping_list_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.shopping_lists.id", ondelete="CASCADE"), nullable=False
    )
    ingredient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.ingredients.id"), nullable=True
    )
    raw_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    store: Mapped[str | None] = mapped_column(String(120), nullable=True)
    estimated_price_usd: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    actual_price_usd: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    # pending | purchased | skipped


# ---------- Preservation (Tier A expansion) ----------

class PreservationJob(Base, TimestampMixin):
    """Canning, freezing, dehydrating, fermenting, pickling. Has safety constraints."""
    __tablename__ = "preservation_jobs"
    __table_args__ = {"schema": "food"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False, index=True
    )
    source_pantry_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.pantry_items.id"), nullable=True
    )
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    # canning_water_bath | canning_pressure | freezing | dehydrating | fermenting | pickling | curing
    ingredient_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity_in: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    quantity_out: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    storage_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.pantry_locations.id"), nullable=True
    )
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    safety_check_passed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    safety_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_urls: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


# ---------- Food waste tracking ----------

class FoodWasteEvent(Base, TimestampMixin):
    __tablename__ = "food_waste_events"
    __table_args__ = {"schema": "food"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False, index=True
    )
    pantry_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.pantry_items.id"), nullable=True
    )
    ingredient_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # spoiled | forgotten | over_cooked | over_purchased | other
    estimated_value_usd: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
