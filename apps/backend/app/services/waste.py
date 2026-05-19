"""
Food waste logging + savings rollup.

`log_waste` creates a FoodWasteEvent, soft-deletes (or decrements) the linked
pantry item, and emits food.pantry_item.wasted.

`savings_rollup` aggregates last-30-day food.meal.cooked payloads (estimated
value of pantry usage) and food.pantry_item.wasted payloads to give a net
savings number — the unit of value the user sees.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import asc, nulls_last
from sqlalchemy.orm import Session

from app.models.core import Event, Household
from app.models.food import FoodWasteEvent, PantryItem
from app.schemas.food import SavingsRollup, WasteLogRequest
from app.services.events import emit_event


def log_waste(
    db: Session,
    *,
    household: Household,
    user_id,
    request: WasteLogRequest,
) -> FoodWasteEvent:
    """Record a waste event. If linked to a pantry item, decrement or soft-delete it."""
    pantry_item: PantryItem | None = (
        db.get(PantryItem, request.pantry_item_id) if request.pantry_item_id else None
    )
    if pantry_item is not None and pantry_item.household_id != household.id:
        pantry_item = None  # Don't trust other-household IDs

    waste = FoodWasteEvent(
        household_id=household.id,
        pantry_item_id=pantry_item.id if pantry_item else None,
        ingredient_name=request.ingredient_name,
        quantity=request.quantity,
        unit=request.unit,
        reason=request.reason,
        estimated_value_usd=request.estimated_value_usd
        or (
            float(pantry_item.estimated_value)
            if pantry_item and pantry_item.estimated_value is not None
            else None
        ),
        occurred_on=request.occurred_on or date.today(),
    )
    db.add(waste)

    if pantry_item is not None:
        # If quantity unspecified or >= pantry item, soft-delete entirely.
        if (
            request.quantity is None
            or pantry_item.quantity is None
            or float(request.quantity) >= float(pantry_item.quantity)
        ):
            pantry_item.deleted_at = datetime.now(UTC)
        else:
            pantry_item.quantity = float(pantry_item.quantity) - float(request.quantity)

    db.flush()

    emit_event(
        db,
        event_type="food.pantry_item.wasted",
        household_id=household.id,
        user_id=user_id,
        entity_type="food_waste_event",
        entity_id=waste.id,
        payload={
            "ingredient_name": waste.ingredient_name,
            "reason": waste.reason,
            "estimated_value_usd": float(waste.estimated_value_usd)
            if waste.estimated_value_usd is not None
            else None,
            "pantry_item_id": str(pantry_item.id) if pantry_item else None,
        },
    )
    return waste


def savings_rollup(
    db: Session, *, household: Household, period_days: int = 30
) -> SavingsRollup:
    """Aggregate cooked-from-pantry value and waste value over the period."""
    since = datetime.now(UTC) - timedelta(days=period_days)

    events = (
        db.query(Event)
        .filter(
            Event.household_id == household.id,
            Event.created_at >= since,
            Event.event_type.in_(["food.meal.cooked", "food.pantry_item.wasted"]),
        )
        .all()
    )

    cooked_value = 0.0
    cooked_count = 0
    waste_value = 0.0
    waste_count = 0
    for ev in events:
        val = ev.payload.get("estimated_value_usd") if ev.payload else None
        if ev.event_type == "food.meal.cooked":
            cooked_count += 1
            if val is not None:
                cooked_value += float(val)
        elif ev.event_type == "food.pantry_item.wasted":
            waste_count += 1
            if val is not None:
                waste_value += float(val)

    today = date.today()
    expiring = (
        db.query(PantryItem)
        .filter(
            PantryItem.household_id == household.id,
            PantryItem.deleted_at.is_(None),
            PantryItem.expires_at.isnot(None),
            PantryItem.expires_at <= today + timedelta(days=3),
        )
        .order_by(nulls_last(asc(PantryItem.expires_at)))
        .all()
    )

    from app.schemas.food import PantryItemRead

    return SavingsRollup(
        period_days=period_days,
        cooked_from_pantry_value_usd=round(cooked_value, 2),
        waste_value_usd=round(waste_value, 2),
        net_savings_usd=round(cooked_value - waste_value, 2),
        cooked_meals_count=cooked_count,
        waste_events_count=waste_count,
        expiring_soon=[PantryItemRead.model_validate(p) for p in expiring],
    )
