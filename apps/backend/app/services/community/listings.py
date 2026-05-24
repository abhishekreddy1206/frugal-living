"""Listings service — create / update (with editor-scope) / soft-delete + the
`reconcile_listings_for_item` hook that the items service calls when an item
is soft-deleted or its quantity changes."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.community import (
    CommunityItem,
    CommunityMember,
    Listing,
    ListingCommunity,
)
from app.models.core import AuditLog, Household, HouseholdMember, User
from app.services.events import emit_event


class ListingNotFound(Exception):
    pass


class OneActiveListingPerItem(Exception):
    """Partial unique index `ux_one_active_listing_per_item` was violated."""


class QuantityExceedsItem(Exception):
    pass


class CommunityNotPermittedForListing(Exception):
    """User tried to add a listing to a community they aren't a member of."""


class NotHouseholdMember(Exception):
    pass


def _require_household_member(db: Session, *, user: User, household: Household) -> HouseholdMember:
    """Caller must be `owner` or `member` (not `viewer`) of the household."""
    m = (
        db.query(HouseholdMember)
        .filter_by(user_id=user.id, household_id=household.id)
        .one_or_none()
    )
    if m is None or m.role not in ("owner", "member"):
        raise NotHouseholdMember(f"user {user.id} cannot act on household {household.id}")
    return m


def _user_community_ids(db: Session, user: User) -> set[uuid.UUID]:
    rows = db.query(CommunityMember.community_id).filter(
        CommunityMember.user_id == user.id
    ).all()
    return {r[0] for r in rows}


def _load_item_owned_by(db: Session, *, household: Household, item_id: uuid.UUID) -> CommunityItem:
    item = db.get(CommunityItem, item_id)
    if item is None or item.deleted_at is not None or item.household_id != household.id:
        raise ListingNotFound(f"item {item_id} not found for household {household.id}")
    return item


def get_listing_for_household(
    db: Session, *, household: Household, listing_id: uuid.UUID,
) -> Listing:
    """Load a listing owned (via the item) by the given household. Raises ListingNotFound."""
    listing = db.get(Listing, listing_id)
    if listing is None or listing.deleted_at is not None:
        raise ListingNotFound(str(listing_id))
    item = db.get(CommunityItem, listing.item_id)
    if item is None or item.household_id != household.id:
        raise ListingNotFound(str(listing_id))
    return listing


def _audit(db: Session, *, action: str, user_id, listing_id, payload: dict | None = None) -> None:
    db.add(AuditLog(
        actor_user_id=user_id,
        action=action,
        target_type="listing",
        target_id=listing_id,
        payload=payload or {},
    ))
    db.flush()


def create_listing(
    db: Session,
    *,
    household: Household,
    user: User,
    item_id: uuid.UUID,
    allowed_exchange_types: list[str],
    quantity_available: int,
    community_ids: list[uuid.UUID],
    share_in_radius: bool,
    share_radius_miles: int | None = None,
    description_override: str | None = None,
) -> Listing:
    _require_household_member(db, user=user, household=household)
    item = _load_item_owned_by(db, household=household, item_id=item_id)
    if quantity_available > item.quantity:
        raise QuantityExceedsItem(
            f"listing quantity {quantity_available} > item quantity {item.quantity}"
        )
    user_communities = _user_community_ids(db, user)
    bad = [cid for cid in community_ids if cid not in user_communities]
    if bad:
        raise CommunityNotPermittedForListing(
            f"user {user.id} is not a member of communities {bad}"
        )

    listing = Listing(
        item_id=item.id,
        created_by_user_id=user.id,
        allowed_exchange_types=allowed_exchange_types,
        quantity_available=quantity_available,
        share_in_radius=share_in_radius,
        share_radius_miles=share_radius_miles,
        availability_status="available",
        description_override=description_override,
    )
    db.add(listing)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise OneActiveListingPerItem(str(item_id)) from None

    for cid in community_ids:
        db.add(ListingCommunity(
            listing_id=listing.id, community_id=cid, added_by_user_id=user.id,
        ))
    db.flush()

    emit_event(
        db,
        event_type="community.listing.created",
        household_id=household.id,
        user_id=user.id,
        entity_type="listing",
        entity_id=listing.id,
        payload={
            "item_id": str(item.id),
            "allowed_exchange_types": allowed_exchange_types,
            "share_in_radius": share_in_radius,
            "community_count": len(community_ids),
        },
    )
    _audit(db, action="community.listing.created", user_id=user.id, listing_id=listing.id,
           payload={"item_id": str(item.id)})
    return listing


def update_listing(
    db: Session,
    *,
    household: Household,
    user: User,
    listing_id: uuid.UUID,
    allowed_exchange_types: list[str] | None = None,
    quantity_available: int | None = None,
    community_ids: list[uuid.UUID] | None = None,
    share_in_radius: bool | None = None,
    share_radius_miles: int | None = None,
    description_override: str | None = None,
    availability_status: str | None = None,
) -> Listing:
    _require_household_member(db, user=user, household=household)
    listing = get_listing_for_household(db, household=household, listing_id=listing_id)
    item = db.get(CommunityItem, listing.item_id)
    assert item is not None  # checked by get_listing_for_household

    changed: dict[str, object] = {}
    if allowed_exchange_types is not None:
        listing.allowed_exchange_types = allowed_exchange_types
        changed["allowed_exchange_types"] = allowed_exchange_types
    if quantity_available is not None:
        if quantity_available > item.quantity:
            raise QuantityExceedsItem(
                f"listing quantity {quantity_available} > item quantity {item.quantity}"
            )
        listing.quantity_available = quantity_available
        changed["quantity_available"] = quantity_available
    if share_in_radius is not None:
        listing.share_in_radius = share_in_radius
        changed["share_in_radius"] = share_in_radius
    if share_radius_miles is not None:
        listing.share_radius_miles = share_radius_miles
        changed["share_radius_miles"] = share_radius_miles
    if description_override is not None:
        listing.description_override = description_override
        changed["description_override"] = description_override
    if availability_status is not None:
        listing.availability_status = availability_status
        changed["availability_status"] = availability_status

    if community_ids is not None:
        # Editor-scope check: any community being *added* must be in the editor's
        # current memberships. Removals are always allowed.
        current = {
            r.community_id for r in
            db.query(ListingCommunity).filter_by(listing_id=listing.id).all()
        }
        desired = set(community_ids)
        added = desired - current
        if added:
            user_communities = _user_community_ids(db, user)
            forbidden = [cid for cid in added if cid not in user_communities]
            if forbidden:
                raise CommunityNotPermittedForListing(
                    f"user {user.id} is not a member of communities {forbidden}"
                )
        # Apply removals, then additions.
        for cid in current - desired:
            db.query(ListingCommunity).filter_by(
                listing_id=listing.id, community_id=cid
            ).delete()
        for cid in added:
            db.add(ListingCommunity(
                listing_id=listing.id, community_id=cid, added_by_user_id=user.id,
            ))
        changed["community_ids"] = sorted(str(c) for c in desired)

    if changed:
        db.flush()
        emit_event(
            db,
            event_type="community.listing.updated",
            household_id=household.id,
            user_id=user.id,
            entity_type="listing",
            entity_id=listing.id,
            payload={"changed": list(changed.keys())},
        )
    return listing


def soft_delete_listing(
    db: Session, *, household: Household, user: User, listing_id: uuid.UUID,
    reason: str = "user_request",
) -> Listing:
    _require_household_member(db, user=user, household=household)
    listing = get_listing_for_household(db, household=household, listing_id=listing_id)
    listing.deleted_at = datetime.now(UTC)
    listing.availability_status = "removed"
    db.flush()
    emit_event(
        db,
        event_type="community.listing.removed",
        household_id=household.id,
        user_id=user.id,
        entity_type="listing",
        entity_id=listing.id,
        payload={"reason": reason},
    )
    return listing


def reconcile_listings_for_item(
    db: Session, *, item: CommunityItem, actor_user_id: uuid.UUID,
) -> None:
    """Called by the items service when an item is soft-deleted or its quantity changes.

    Behaviors:
    - Item soft-deleted (item.deleted_at is not None) -> soft-delete the active listing.
    - Item quantity dropped to 0 -> soft-delete the active listing.
    - Item quantity reduced but >0 -> cap listing.quantity_available.
    No-op when no active listing exists.
    """
    listing = (
        db.query(Listing)
        .filter(
            Listing.item_id == item.id,
            Listing.deleted_at.is_(None),
            Listing.availability_status != "removed",
        )
        .one_or_none()
    )
    if listing is None:
        return

    now = datetime.now(UTC)
    if item.deleted_at is not None or item.quantity <= 0:
        listing.deleted_at = now
        listing.availability_status = "removed"
        db.flush()
        emit_event(
            db,
            event_type="community.listing.removed",
            household_id=item.household_id,
            user_id=actor_user_id,
            entity_type="listing",
            entity_id=listing.id,
            payload={"reason": "item_cascade"},
        )
        return

    # Cap quantity if item quantity dropped below the listing's offer.
    if listing.quantity_available > item.quantity:
        listing.quantity_available = item.quantity
        db.flush()
        emit_event(
            db,
            event_type="community.listing.updated",
            household_id=item.household_id,
            user_id=actor_user_id,
            entity_type="listing",
            entity_id=listing.id,
            payload={"changed": ["quantity_available"], "reason": "item_cascade"},
        )
