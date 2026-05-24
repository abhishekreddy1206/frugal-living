"""Tests for the listings service + the items.py cascade hooks."""
from __future__ import annotations

import uuid

import pytest

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.community import ListingCommunity
from app.models.core import Event, Household, User
from app.services.community import communities as community_svc
from app.services.community import items as items_svc
from app.services.community import listings as svc
from app.services.community.listings import (
    CommunityNotPermittedForListing,
    OneActiveListingPerItem,
    QuantityExceedsItem,
)


def _ctx(db):
    return db.get(Household, DEV_HOUSEHOLD_ID), db.get(User, DEV_USER_ID)


def test_create_listing_minimal(db):
    h, u = _ctx(db)
    item = items_svc.create_item(db, household=h, user=u, name="Drill", quantity=1)
    listing = svc.create_listing(
        db, household=h, user=u, item_id=item.id,
        allowed_exchange_types=["borrow"], quantity_available=1,
        community_ids=[], share_in_radius=False,
    )
    assert listing.availability_status == "available"
    assert listing.share_in_radius is False
    assert db.query(Event).filter_by(event_type="community.listing.created").count() == 1


def test_create_listing_rejects_quantity_exceeding_item(db):
    h, u = _ctx(db)
    item = items_svc.create_item(db, household=h, user=u, name="Chairs", quantity=4)
    with pytest.raises(QuantityExceedsItem):
        svc.create_listing(
            db, household=h, user=u, item_id=item.id,
            allowed_exchange_types=["borrow"], quantity_available=5,
            community_ids=[], share_in_radius=False,
        )


def test_create_listing_rejects_community_user_not_in(db):
    h, u = _ctx(db)
    other_user = User(id=uuid.uuid4(), email=f"x-{uuid.uuid4().hex[:6]}@x.com", display_name="x")
    db.add(other_user)
    db.flush()
    item = items_svc.create_item(db, household=h, user=u, name="Tent", quantity=1)
    c = community_svc.create_community(db, creator_user=other_user, slug="foreign", name="Foreign")
    with pytest.raises(CommunityNotPermittedForListing):
        svc.create_listing(
            db, household=h, user=u, item_id=item.id,
            allowed_exchange_types=["borrow"], quantity_available=1,
            community_ids=[c.id], share_in_radius=False,
        )


def test_create_listing_with_user_community(db):
    h, u = _ctx(db)
    c = community_svc.create_community(db, creator_user=u, slug="mine", name="Mine")
    item = items_svc.create_item(db, household=h, user=u, name="Tent", quantity=1)
    listing = svc.create_listing(
        db, household=h, user=u, item_id=item.id,
        allowed_exchange_types=["borrow"], quantity_available=1,
        community_ids=[c.id], share_in_radius=False,
    )
    assert (
        db.query(ListingCommunity)
        .filter_by(listing_id=listing.id, community_id=c.id)
        .count() == 1
    )


def test_create_listing_one_active_per_item(db):
    h, u = _ctx(db)
    item = items_svc.create_item(db, household=h, user=u, name="Catan", quantity=1)
    svc.create_listing(
        db, household=h, user=u, item_id=item.id,
        allowed_exchange_types=["borrow"], quantity_available=1,
        community_ids=[], share_in_radius=False,
    )
    with pytest.raises(OneActiveListingPerItem):
        svc.create_listing(
            db, household=h, user=u, item_id=item.id,
            allowed_exchange_types=["gift"], quantity_available=1,
            community_ids=[], share_in_radius=False,
        )


def test_soft_delete_item_cascades_to_listing(db):
    """Audit fix #1 — soft-deleting an item soft-deletes its active listing."""
    h, u = _ctx(db)
    item = items_svc.create_item(db, household=h, user=u, name="Saw", quantity=1)
    listing = svc.create_listing(
        db, household=h, user=u, item_id=item.id,
        allowed_exchange_types=["borrow"], quantity_available=1,
        community_ids=[], share_in_radius=False,
    )
    items_svc.soft_delete_item(db, household=h, user=u, item_id=item.id)
    db.refresh(listing)
    assert listing.deleted_at is not None
    assert listing.availability_status == "removed"
    assert db.query(Event).filter_by(event_type="community.listing.removed").count() == 1


def test_update_item_quantity_reconciles_listing(db):
    """Audit fix #7 — reducing item.quantity caps the listing's quantity_available."""
    h, u = _ctx(db)
    item = items_svc.create_item(db, household=h, user=u, name="Chairs", quantity=8)
    listing = svc.create_listing(
        db, household=h, user=u, item_id=item.id,
        allowed_exchange_types=["borrow"], quantity_available=6,
        community_ids=[], share_in_radius=False,
    )
    items_svc.update_item(db, household=h, user=u, item_id=item.id, quantity=3)
    db.refresh(listing)
    assert listing.quantity_available == 3


def test_update_item_quantity_to_zero_removes_listing(db):
    h, u = _ctx(db)
    item = items_svc.create_item(db, household=h, user=u, name="X", quantity=2)
    listing = svc.create_listing(
        db, household=h, user=u, item_id=item.id,
        allowed_exchange_types=["gift"], quantity_available=2,
        community_ids=[], share_in_radius=False,
    )
    items_svc.update_item(db, household=h, user=u, item_id=item.id, quantity=0)
    db.refresh(listing)
    assert listing.deleted_at is not None
    assert listing.availability_status == "removed"


def test_update_listing_editor_can_only_add_communities_they_belong_to(db):
    """Audit fix #3 — Bob can't add a community Bob isn't in, even if Alice (the
    original creator) was in it."""
    h, u = _ctx(db)  # u is Alice (DEV_USER)
    alice_community = community_svc.create_community(db, creator_user=u, slug="ac", name="Alice's")
    item = items_svc.create_item(db, household=h, user=u, name="Item", quantity=1)
    listing = svc.create_listing(
        db, household=h, user=u, item_id=item.id,
        allowed_exchange_types=["borrow"], quantity_available=1,
        community_ids=[alice_community.id], share_in_radius=False,
    )
    # Now Bob — another user — is a member of the same household but NOT of any community.
    from app.models.core import HouseholdMember
    bob = User(id=uuid.uuid4(), email=f"b-{uuid.uuid4().hex[:6]}@x.com", display_name="Bob")
    db.add(bob)
    db.flush()
    db.add(HouseholdMember(user_id=bob.id, household_id=h.id, role="member"))
    db.flush()
    # A community Bob isn't in (someone else owns it)
    other = User(id=uuid.uuid4(), email=f"o-{uuid.uuid4().hex[:6]}@x.com", display_name="O")
    db.add(other)
    db.flush()
    other_community = community_svc.create_community(
        db, creator_user=other, slug="oc", name="Other's"
    )
    # Bob tries to add other_community to the listing — must be rejected.
    with pytest.raises(CommunityNotPermittedForListing):
        svc.update_listing(
            db, household=h, user=bob, listing_id=listing.id,
            community_ids=[alice_community.id, other_community.id],
        )
    # But Bob CAN remove alice_community (existing pick), even though he isn't in it.
    svc.update_listing(
        db, household=h, user=bob, listing_id=listing.id, community_ids=[],
    )
    assert (
        db.query(ListingCommunity).filter_by(listing_id=listing.id).count() == 0
    )


def test_soft_delete_listing(db):
    h, u = _ctx(db)
    item = items_svc.create_item(db, household=h, user=u, name="X", quantity=1)
    listing = svc.create_listing(
        db, household=h, user=u, item_id=item.id,
        allowed_exchange_types=["gift"], quantity_available=1,
        community_ids=[], share_in_radius=False,
    )
    svc.soft_delete_listing(db, household=h, user=u, listing_id=listing.id)
    db.refresh(listing)
    assert listing.deleted_at is not None
    assert listing.availability_status == "removed"
