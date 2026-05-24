"""Model roundtrip tests for the Phase 2 community tables."""
from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.community import (
    Community,
    CommunityItem,
    CommunityJoinRequest,
    CommunityMember,
    Listing,
    ListingCommunity,
)


def test_community_roundtrip(db):
    c = Community(
        slug="park-slope-tools",
        name="Park Slope Tools",
        description="A neighborhood tool library",
        created_by_user_id=DEV_USER_ID,
    )
    db.add(c)
    db.flush()
    fetched = db.get(Community, c.id)
    assert fetched is not None
    assert fetched.slug == "park-slope-tools"
    assert fetched.metadata_ == {}
    assert fetched.deleted_at is None


def test_community_member_unique(db):
    c = Community(slug="t1", name="t1", created_by_user_id=DEV_USER_ID)
    db.add(c)
    db.flush()
    db.add(CommunityMember(community_id=c.id, user_id=DEV_USER_ID, role="owner"))
    db.flush()
    # Same (community, user) again should fail.
    db.add(CommunityMember(community_id=c.id, user_id=DEV_USER_ID, role="member"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_join_request_partial_unique_pending(db):
    c = Community(slug="t2", name="t2", created_by_user_id=DEV_USER_ID)
    db.add(c)
    db.flush()
    db.add(CommunityJoinRequest(community_id=c.id, user_id=DEV_USER_ID, status="pending"))
    db.flush()
    # Second pending for same (community, user) should fail.
    db.add(CommunityJoinRequest(community_id=c.id, user_id=DEV_USER_ID, status="pending"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_listing_one_active_per_item(db):
    item = CommunityItem(household_id=DEV_HOUSEHOLD_ID, created_by_user_id=DEV_USER_ID, name="Drill")
    db.add(item)
    db.flush()
    db.add(Listing(
        item_id=item.id,
        created_by_user_id=DEV_USER_ID,
        allowed_exchange_types=["borrow"],
        quantity_available=1,
        availability_status="available",
    ))
    db.flush()
    # Second active listing for the same item should fail (partial unique index).
    db.add(Listing(
        item_id=item.id,
        created_by_user_id=DEV_USER_ID,
        allowed_exchange_types=["gift"],
        quantity_available=1,
        availability_status="available",
    ))
    with pytest.raises(IntegrityError):
        db.flush()


def test_listing_community_join_roundtrip(db):
    item = CommunityItem(household_id=DEV_HOUSEHOLD_ID, created_by_user_id=DEV_USER_ID, name="Tent")
    c = Community(slug="t3", name="t3", created_by_user_id=DEV_USER_ID)
    db.add(item)
    db.add(c)
    db.flush()
    listing = Listing(
        item_id=item.id,
        created_by_user_id=DEV_USER_ID,
        allowed_exchange_types=["borrow"],
        quantity_available=1,
        availability_status="available",
    )
    db.add(listing)
    db.flush()
    db.add(ListingCommunity(listing_id=listing.id, community_id=c.id, added_by_user_id=DEV_USER_ID))
    db.flush()
