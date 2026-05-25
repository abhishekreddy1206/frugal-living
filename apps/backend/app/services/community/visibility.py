"""The canonical 'listings visible to (viewer)' query.

This is the single security gate for every cross-household read in Phase 2.
Every endpoint that surfaces another household's listing data MUST funnel
through `listings_visible_to(...)` — no exceptions.

Visibility = community-path OR radius-path, subject to liveness filters
(audit fixes #1, #2, #4):
  - listing.deleted_at IS NULL AND availability_status = 'available'
  - item.deleted_at IS NULL
  - owning household != viewer household
  - all traversed users are users.is_active = true
  - all traversed communities are communities.deleted_at IS NULL
  - community path: at least one *current* member of the owning household is
    also a current member of a community the listing is shared into
  - radius path: listing.share_in_radius = true AND distance(viewer.lat/lng,
    owner.lat/lng) <= effective_radius_miles (COALESCE listing → owner → 5)
"""
from __future__ import annotations

import math

from sqlalchemy import Float, and_, exists, or_, select
from sqlalchemy.orm import Query, Session, aliased

from app.models.community import (
    Community,
    CommunityItem,
    CommunityMember,
    Listing,
    ListingCommunity,
)
from app.models.core import Household, HouseholdMember, User

DEFAULT_SHARE_RADIUS_MILES = 5

# Rough miles per degree latitude (constant); longitude varies with cos(lat).
_MILES_PER_DEGREE_LAT = 69.0


def _bounding_box(lat: float, lng: float, miles: float) -> tuple[float, float, float, float]:
    """(min_lat, max_lat, min_lng, max_lng) bracketing a circle of `miles` around (lat, lng)."""
    lat_delta = miles / _MILES_PER_DEGREE_LAT
    cos_lat = max(0.01, math.cos(math.radians(lat)))
    lng_delta = miles / (_MILES_PER_DEGREE_LAT * cos_lat)
    return (lat - lat_delta, lat + lat_delta, lng - lng_delta, lng + lng_delta)


def _haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in miles. Used for the final exact filter inside the bounding box."""
    R = 3958.8  # mean Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _household_lat_lng(household: Household) -> tuple[float, float] | None:
    md = household.metadata_ or {}
    lat = md.get("lat")
    lng = md.get("lng")
    if lat is None or lng is None:
        return None
    return float(lat), float(lng)


def _household_default_radius(household: Household) -> int:
    md = household.metadata_ or {}
    v = md.get("share_radius_miles")
    if v is None:
        return DEFAULT_SHARE_RADIUS_MILES
    return int(v)


def listings_visible_to(
    db: Session, *, viewer_household: Household, viewer_user: User,
) -> Query[Listing]:
    """Return a Query of Listings visible to this (household, user). Callers may
    `.filter(...)` / `.order_by(...)` / `.limit(...)` on top — but the security
    gate is already inside this query and must not be bypassed."""

    OwnerHM = aliased(HouseholdMember)
    OwnerUser = aliased(User)
    SharedMember = aliased(CommunityMember)
    SharedMemberUser = aliased(User)

    # The community path: there exists a (listing_communities) row pointing at a
    # live community where at least one current member of the owning household
    # (whose user is active) is also a current member of that community.
    community_exists = (
        select(1)
        .select_from(ListingCommunity)
        .join(Community, Community.id == ListingCommunity.community_id)
        .join(OwnerHM, OwnerHM.household_id == CommunityItem.household_id)
        .join(OwnerUser, OwnerUser.id == OwnerHM.user_id)
        .join(
            SharedMember,
            and_(
                SharedMember.community_id == ListingCommunity.community_id,
                SharedMember.user_id == OwnerHM.user_id,
            ),
        )
        .join(SharedMemberUser, SharedMemberUser.id == SharedMember.user_id)
        .where(
            ListingCommunity.listing_id == Listing.id,
            Community.deleted_at.is_(None),
            OwnerUser.is_active.is_(True),
            SharedMemberUser.is_active.is_(True),
            # Also require: the viewer is a current member of that community.
            exists(
                select(1).where(
                    CommunityMember.community_id == ListingCommunity.community_id,
                    CommunityMember.user_id == viewer_user.id,
                )
            ),
        )
        .exists()
    )

    base = (
        db.query(Listing)
        .join(CommunityItem, CommunityItem.id == Listing.item_id)
        .filter(
            Listing.deleted_at.is_(None),
            Listing.availability_status == "available",
            CommunityItem.deleted_at.is_(None),
            CommunityItem.household_id != viewer_household.id,
        )
    )

    viewer_loc = _household_lat_lng(viewer_household)
    if viewer_loc is None:
        # No location → only community path is possible.
        return base.filter(community_exists)

    # Radius path: bounding box + exact distance check.
    # Use a generous outer box (max allowed user radius is 500 mi per schema) to
    # let Postgres narrow first; then a Python-side exact filter excludes corner cases.
    viewer_lat, viewer_lng = viewer_loc
    max_outer_radius = 500
    min_lat, max_lat, min_lng, max_lng = _bounding_box(viewer_lat, viewer_lng, max_outer_radius)
    # Cast JSONB values to float for comparison.
    OwnerHousehold = aliased(Household)
    lat_expr = OwnerHousehold.metadata_["lat"].astext.cast(Float)
    lng_expr = OwnerHousehold.metadata_["lng"].astext.cast(Float)

    box_subq = (
        db.query(Listing.id)
        .join(CommunityItem, CommunityItem.id == Listing.item_id)
        .join(OwnerHousehold, OwnerHousehold.id == CommunityItem.household_id)
        .filter(
            Listing.share_in_radius.is_(True),
            lat_expr.is_not(None),
            lng_expr.is_not(None),
            lat_expr.between(min_lat, max_lat),
            lng_expr.between(min_lng, max_lng),
            Listing.deleted_at.is_(None),
            Listing.availability_status == "available",
            CommunityItem.deleted_at.is_(None),
            CommunityItem.household_id != viewer_household.id,
        )
        .subquery()
    )

    box_q = db.query(Listing).filter(Listing.id.in_(select(box_subq.c.id)))
    box_candidates = box_q.all()

    radius_passing_ids: list = []
    for listing in box_candidates:
        item = db.get(CommunityItem, listing.item_id)
        if item is None:
            continue
        owner_h = db.get(Household, item.household_id)
        if owner_h is None:
            continue
        owner_loc = _household_lat_lng(owner_h)
        if owner_loc is None:
            continue
        distance = _haversine_miles(viewer_lat, viewer_lng, owner_loc[0], owner_loc[1])
        effective = (
            listing.share_radius_miles
            if listing.share_radius_miles is not None
            else _household_default_radius(owner_h)
        )
        if distance <= effective:
            radius_passing_ids.append(listing.id)

    if radius_passing_ids:
        return base.filter(or_(community_exists, Listing.id.in_(radius_passing_ids)))
    return base.filter(community_exists)


def distance_for(viewer_household: Household, owner_household: Household) -> float | None:
    """Compute the rounded distance for a feed row's `distance_miles` field.
    Returns None when either household lacks a location."""
    v = _household_lat_lng(viewer_household)
    o = _household_lat_lng(owner_household)
    if v is None or o is None:
        return None
    return round(_haversine_miles(v[0], v[1], o[0], o[1]), 1)
