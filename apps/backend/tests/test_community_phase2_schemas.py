"""Validation tests for Phase 2 schemas."""
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.community import (
    CommunityCreate,
    JoinRequestDecideRequest,
    ListingCreate,
    ListingUpdate,
)


def test_community_create_rejects_bad_slug():
    with pytest.raises(ValidationError):
        CommunityCreate(slug="Has Spaces", name="x")
    with pytest.raises(ValidationError):
        CommunityCreate(slug="a", name="x")  # too short
    with pytest.raises(ValidationError):
        CommunityCreate(slug="UPPER", name="x")  # uppercase


def test_community_create_accepts_valid_slug():
    c = CommunityCreate(slug="park-slope-tools", name="Park Slope Tools")
    assert c.slug == "park-slope-tools"


def test_listing_create_requires_at_least_one_exchange_type():
    with pytest.raises(ValidationError):
        ListingCreate(item_id=uuid.uuid4(), allowed_exchange_types=[], quantity_available=1)


def test_listing_create_rejects_unknown_exchange_type():
    with pytest.raises(ValidationError):
        ListingCreate(
            item_id=uuid.uuid4(),
            allowed_exchange_types=["sell"],  # not allowed
            quantity_available=1,
        )


def test_listing_create_accepts_borrow_swap_gift():
    lc = ListingCreate(
        item_id=uuid.uuid4(),
        allowed_exchange_types=["borrow", "gift"],
        quantity_available=2,
        community_ids=[uuid.uuid4()],
        share_in_radius=True,
    )
    assert lc.quantity_available == 2


def test_listing_update_all_optional():
    ListingUpdate()  # empty patch is valid


def test_decide_request_note_optional():
    JoinRequestDecideRequest()  # no note
    JoinRequestDecideRequest(note="not yet")
