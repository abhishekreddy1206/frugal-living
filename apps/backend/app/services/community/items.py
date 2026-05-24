"""
Community inventory item helpers — Tier B Phase 1.

Create / update / soft-delete / list a household's inventory items, each
emitting the matching `community.item.*` event. Mirrors app/services/pantry.py.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.models.community import CommunityItem
from app.models.core import Household, User
from app.schemas.community import ITEM_CATEGORIES, ITEM_CONDITIONS
from app.services.events import emit_event


# Avoid a top-level circular import: listings.py imports from this file too.
def _reconcile_listings(db: Session, *, item: CommunityItem, actor_user_id) -> None:
    from app.services.community.listings import reconcile_listings_for_item
    reconcile_listings_for_item(db, item=item, actor_user_id=actor_user_id)


class CommunityItemNotFound(Exception):
    """Raised when an item id can't be resolved for the household."""


def _normalize_category(category: str | None) -> str:
    if category and category.strip().lower() in ITEM_CATEGORIES:
        return category.strip().lower()
    return "other"


def _normalize_condition(condition: str | None) -> str | None:
    if condition and condition.strip().lower() in ITEM_CONDITIONS:
        return condition.strip().lower()
    return None


def _load_owned_item(
    db: Session, household: Household, item_id: uuid.UUID
) -> CommunityItem:
    item = db.get(CommunityItem, item_id)
    if item is None or item.household_id != household.id or item.deleted_at is not None:
        raise CommunityItemNotFound(str(item_id))
    return item


def list_items(
    db: Session, *, household: Household, category: str | None = None
) -> list[CommunityItem]:
    """List a household's non-deleted items, newest first; optional category filter."""
    query = db.query(CommunityItem).filter(
        CommunityItem.household_id == household.id,
        CommunityItem.deleted_at.is_(None),
    )
    if category is not None:
        query = query.filter(CommunityItem.category == _normalize_category(category))
    return query.order_by(CommunityItem.created_at.desc()).all()


def create_item(
    db: Session,
    *,
    household: Household,
    user: User,
    name: str,
    category: str = "other",
    tags: list[str] | None = None,
    quantity: int | None = 1,
    condition: str | None = None,
    estimated_value_usd: float | None = None,
    location: str | None = None,
    acquired_on: date | None = None,
    notes: str | None = None,
    source: str = "manual",
    confidence: float | None = None,
    photo_url: str | None = None,
) -> CommunityItem:
    """Create an inventory item and emit community.item.added."""
    item = CommunityItem(
        household_id=household.id,
        created_by_user_id=user.id,
        name=name,
        category=_normalize_category(category),
        tags=tags or [],
        quantity=quantity if quantity is not None else 1,
        condition=_normalize_condition(condition),
        estimated_value_usd=estimated_value_usd,
        location=location,
        acquired_on=acquired_on,
        notes=notes,
        source=source,
        confidence=confidence,
        photo_url=photo_url,
    )
    db.add(item)
    db.flush()

    emit_event(
        db,
        event_type="community.item.added",
        household_id=household.id,
        user_id=user.id,
        entity_type="item",
        entity_id=item.id,
        payload={
            "name": item.name,
            "category": item.category,
            "quantity": item.quantity,
            "source": source,
        },
    )
    return item


def update_item(
    db: Session,
    *,
    household: Household,
    user: User,
    item_id: uuid.UUID,
    name: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    quantity: int | None = None,
    condition: str | None = None,
    estimated_value_usd: float | None = None,
    location: str | None = None,
    acquired_on: date | None = None,
    notes: str | None = None,
) -> CommunityItem:
    """Update supplied fields of an item; emit community.item.updated."""
    item = _load_owned_item(db, household, item_id)
    changed: dict[str, object] = {}
    if name is not None:
        item.name = name
        changed["name"] = name
    if category is not None:
        item.category = _normalize_category(category)
        changed["category"] = item.category
    if tags is not None:
        item.tags = tags
        changed["tags"] = tags
    if quantity is not None:
        item.quantity = quantity
        changed["quantity"] = quantity
    if condition is not None:
        item.condition = _normalize_condition(condition)
        changed["condition"] = item.condition
    if estimated_value_usd is not None:
        item.estimated_value_usd = estimated_value_usd
        changed["estimated_value_usd"] = estimated_value_usd
    if location is not None:
        item.location = location
        changed["location"] = location
    if acquired_on is not None:
        item.acquired_on = acquired_on
        changed["acquired_on"] = acquired_on.isoformat()
    if notes is not None:
        item.notes = notes
        changed["notes"] = notes
    if not changed:
        return item  # no-op update — don't emit a spurious event
    db.flush()
    if "quantity" in changed:
        _reconcile_listings(db, item=item, actor_user_id=user.id)

    emit_event(
        db,
        event_type="community.item.updated",
        household_id=household.id,
        user_id=user.id,
        entity_type="item",
        entity_id=item.id,
        payload={"name": item.name, "changed": changed},
    )
    return item


def soft_delete_item(
    db: Session, *, household: Household, user: User, item_id: uuid.UUID
) -> CommunityItem:
    """Soft-delete an item (sets deleted_at); emit community.item.removed."""
    item = _load_owned_item(db, household, item_id)
    item.deleted_at = datetime.now(UTC)
    db.flush()
    _reconcile_listings(db, item=item, actor_user_id=user.id)

    emit_event(
        db,
        event_type="community.item.removed",
        household_id=household.id,
        user_id=user.id,
        entity_type="item",
        entity_id=item.id,
        payload={"name": item.name},
    )
    return item
