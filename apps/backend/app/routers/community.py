"""Tier B — community routes. Phase 1: household inventory."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel as _BaseModel
from sqlalchemy.orm import Session

from app.auth import CurrentHousehold, CurrentUser
from app.db import get_db
from app.models.community import (
    CommunityItem,
    CommunityJoinRequest,
    CommunityMember,
    Listing,
    ListingCommunity,
)
from app.models.core import Household
from app.schemas.community import (
    CommunityCreate,
    CommunityMembershipRead,
    CommunityPreview,
    CommunityRead,
    CommunityUpdate,
    FeedResponse,
    FeedRow,
    ItemCaptureRequest,
    ItemCaptureResponse,
    ItemCreate,
    ItemRead,
    ItemUpdate,
    JoinRequestDecideRequest,
    JoinRequestRead,
    ListingCreate,
    ListingItemSummary,
    ListingRead,
    ListingUpdate,
    MyCommunitiesResponse,
)
from app.services.community import communities as community_svc
from app.services.community import items as items_service
from app.services.community import join_requests as jr_svc
from app.services.community import listings as listings_svc
from app.services.community.communities import (
    CommunityNotFound,
    CommunitySlugTaken,
    NotACommunityMember,
    SoleOwnerCannotLeave,
)
from app.services.community.items import CommunityItemNotFound
from app.services.community.join_requests import (
    AlreadyAMember,
    AlreadyDecided,
    AlreadyPending,
    JoinRequestNotFound,
    get_request_or_404,
)
from app.services.community.listings import (
    CommunityNotPermittedForListing,
    NotHouseholdMember,
    OneActiveListingPerItem,
    QuantityExceedsItem,
)
from app.services.community.listings import (
    ListingNotFound as _ListingNotFound,
)
from app.services.community.visibility import (
    distance_for,
    listings_visible_to,
)
from app.services.llm import extract_items_from_image

router = APIRouter()


# ---------------------------------------------------------------------------
# Listings helper
# ---------------------------------------------------------------------------

def _listing_read(db: Session, listing: Listing) -> ListingRead:
    item = db.get(CommunityItem, listing.item_id)
    assert item is not None
    community_ids = [
        lc.community_id for lc in
        db.query(ListingCommunity).filter_by(listing_id=listing.id).all()
    ]
    return ListingRead(
        id=listing.id,
        item=ListingItemSummary(
            id=item.id, name=item.name, category=item.category, tags=item.tags or [],
            quantity=item.quantity, condition=item.condition,
            estimated_value_usd=(
                float(item.estimated_value_usd) if item.estimated_value_usd is not None else None
            ),
            photo_url=item.photo_url, notes=item.notes,
        ),
        allowed_exchange_types=listing.allowed_exchange_types,
        quantity_available=listing.quantity_available,
        share_in_radius=listing.share_in_radius,
        share_radius_miles=listing.share_radius_miles,
        availability_status=listing.availability_status,
        description_override=listing.description_override,
        community_ids=community_ids,
        created_at=listing.created_at,
    )


# ---------------------------------------------------------------------------
# Listings endpoints
# NOTE: GET /listings/mine MUST be registered BEFORE GET /listings/{listing_id}
#       so that "mine" is not captured as a UUID.
# ---------------------------------------------------------------------------

@router.post("/listings", response_model=ListingRead)
def create_listing_endpoint(
    request: ListingCreate,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ListingRead:
    try:
        listing = listings_svc.create_listing(
            db, household=household, user=user, item_id=request.item_id,
            allowed_exchange_types=request.allowed_exchange_types,
            quantity_available=request.quantity_available,
            community_ids=request.community_ids,
            share_in_radius=request.share_in_radius,
            share_radius_miles=request.share_radius_miles,
            description_override=request.description_override,
        )
    except _ListingNotFound:
        raise HTTPException(status_code=404, detail="item not found for your household") from None
    except QuantityExceedsItem as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    except CommunityNotPermittedForListing as e:
        raise HTTPException(status_code=403, detail=str(e)) from None
    except OneActiveListingPerItem:
        raise HTTPException(
            status_code=409, detail="an active listing already exists for this item",
        ) from None
    except NotHouseholdMember:
        raise HTTPException(status_code=403, detail="must be a household owner or member") from None
    db.commit()
    db.refresh(listing)
    return _listing_read(db, listing)


@router.get("/listings/mine", response_model=list[ListingRead])
def list_mine_endpoint(
    household: CurrentHousehold,
    db: Annotated[Session, Depends(get_db)],
) -> list[ListingRead]:
    rows = (
        db.query(Listing)
        .join(CommunityItem, CommunityItem.id == Listing.item_id)
        .filter(
            CommunityItem.household_id == household.id,
            Listing.deleted_at.is_(None),
        )
        .order_by(Listing.created_at.desc())
        .all()
    )
    return [_listing_read(db, r) for r in rows]


@router.patch("/listings/{listing_id}", response_model=ListingRead)
def update_listing_endpoint(
    listing_id: uuid.UUID,
    request: ListingUpdate,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ListingRead:
    try:
        listing = listings_svc.update_listing(
            db, household=household, user=user, listing_id=listing_id,
            allowed_exchange_types=request.allowed_exchange_types,
            quantity_available=request.quantity_available,
            community_ids=request.community_ids,
            share_in_radius=request.share_in_radius,
            share_radius_miles=request.share_radius_miles,
            description_override=request.description_override,
            availability_status=request.availability_status,
        )
    except _ListingNotFound:
        raise HTTPException(status_code=404, detail="listing not found") from None
    except QuantityExceedsItem as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    except CommunityNotPermittedForListing as e:
        raise HTTPException(status_code=403, detail=str(e)) from None
    except NotHouseholdMember:
        raise HTTPException(status_code=403, detail="must be a household owner or member") from None
    db.commit()
    db.refresh(listing)
    return _listing_read(db, listing)


@router.delete("/listings/{listing_id}")
def delete_listing_endpoint(
    listing_id: uuid.UUID,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    try:
        listings_svc.soft_delete_listing(
            db, household=household, user=user, listing_id=listing_id,
        )
    except _ListingNotFound:
        raise HTTPException(status_code=404, detail="listing not found") from None
    except NotHouseholdMember:
        raise HTTPException(status_code=403, detail="must be a household owner or member") from None
    db.commit()
    return {"status": "deleted"}


@router.get("/listings/{listing_id}", response_model=ListingRead)
def get_listing_endpoint(
    listing_id: uuid.UUID,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ListingRead:
    """Visibility-gated detail. Owners see their own; others see only listings
    the visibility helper returns."""
    listing = db.get(Listing, listing_id)
    if listing is None or listing.deleted_at is not None:
        raise HTTPException(status_code=404, detail="listing not found")
    item = db.get(CommunityItem, listing.item_id)
    if item is not None and item.household_id == household.id:
        # Owner-side read.
        return _listing_read(db, listing)
    # Visibility-gated read.
    from app.services.community.visibility import listings_visible_to
    visible_ids = {
        r.id for r in
        listings_visible_to(db, viewer_household=household, viewer_user=user).all()
    }
    if listing.id not in visible_ids:
        raise HTTPException(status_code=404, detail="listing not found")
    return _listing_read(db, listing)


# ---------------------------------------------------------------------------
# Items endpoints
# ---------------------------------------------------------------------------

@router.get("/items", response_model=list[ItemRead])
def list_items(
    household: CurrentHousehold,
    db: Annotated[Session, Depends(get_db)],
    category: Annotated[str | None, Query()] = None,
) -> list[CommunityItem]:
    """List the current household's inventory, newest first."""
    return items_service.list_items(db, household=household, category=category)


@router.post("/items", response_model=ItemRead)
def create_item(
    request: ItemCreate,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ItemRead:
    """Manually create one inventory item."""
    item = items_service.create_item(
        db,
        household=household,
        user=user,
        name=request.name,
        category=request.category,
        tags=request.tags,
        quantity=request.quantity,
        condition=request.condition,
        estimated_value_usd=request.estimated_value_usd,
        location=request.location,
        acquired_on=request.acquired_on,
        notes=request.notes,
        source="manual",
    )
    db.commit()
    db.refresh(item)
    return ItemRead.model_validate(item)


@router.post("/items/capture", response_model=ItemCaptureResponse)
def capture_items(
    request: ItemCaptureRequest,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ItemCaptureResponse:
    """Photo → inventory items. Sonnet 4.6 vision extracts; we persist + emit events."""
    extracted = extract_items_from_image(request.image_base64, request.media_type)

    created: list[CommunityItem] = []
    for ext in extracted.items:
        item = items_service.create_item(
            db,
            household=household,
            user=user,
            name=ext.name,
            category=ext.category,
            tags=ext.tags,
            quantity=ext.quantity or 1,
            condition=ext.condition,
            estimated_value_usd=ext.estimated_value_usd,
            notes=ext.notes,
            source="photo_capture",
            confidence=ext.confidence,
        )
        created.append(item)

    db.commit()
    for item in created:
        db.refresh(item)

    return ItemCaptureResponse(
        items=[ItemRead.model_validate(item) for item in created],
        created_count=len(created),
    )


@router.patch("/items/{item_id}", response_model=ItemRead)
def update_item(
    item_id: uuid.UUID,
    request: ItemUpdate,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ItemRead:
    """Update an inventory item's fields."""
    try:
        item = items_service.update_item(
            db,
            household=household,
            user=user,
            item_id=item_id,
            name=request.name,
            category=request.category,
            tags=request.tags,
            quantity=request.quantity,
            condition=request.condition,
            estimated_value_usd=request.estimated_value_usd,
            location=request.location,
            acquired_on=request.acquired_on,
            notes=request.notes,
        )
    except CommunityItemNotFound:
        raise HTTPException(404, "item not found") from None
    db.commit()
    db.refresh(item)
    return ItemRead.model_validate(item)


@router.delete("/items/{item_id}")
def delete_item(
    item_id: uuid.UUID,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    """Soft-delete an inventory item."""
    try:
        items_service.soft_delete_item(db, household=household, user=user, item_id=item_id)
    except CommunityItemNotFound:
        raise HTTPException(404, "item not found") from None
    db.commit()
    return {"status": "deleted", "id": str(item_id)}


@router.post("/communities", response_model=CommunityRead)
def create_community_endpoint(
    request: CommunityCreate,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> CommunityRead:
    """Create a community; the caller becomes its `owner`."""
    try:
        c = community_svc.create_community(
            db,
            creator_user=user,
            slug=request.slug,
            name=request.name,
            description=request.description,
        )
    except CommunitySlugTaken:
        raise HTTPException(status_code=409, detail="slug already in use") from None
    db.commit()
    db.refresh(c)
    return CommunityRead.model_validate(c)


@router.get("/communities/mine", response_model=MyCommunitiesResponse)
def my_communities_endpoint(
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> MyCommunitiesResponse:
    rows = community_svc.list_my_communities(db, user=user)
    return MyCommunitiesResponse(
        memberships=[
            CommunityMembershipRead(
                community=CommunityRead.model_validate(c),
                role=m.role,
                joined_at=m.joined_at,
            )
            for c, m in rows
        ]
    )


@router.get("/communities/{slug}", response_model=CommunityPreview)
def get_community_preview_endpoint(
    slug: str,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> CommunityPreview:
    """Preview a community by slug. 404 if not found. No member identities exposed."""
    c = community_svc.get_community_by_slug(db, slug)
    if c is None:
        raise HTTPException(status_code=404, detail="community not found")

    member_count = db.query(CommunityMember).filter_by(community_id=c.id).count()
    my_membership = (
        db.query(CommunityMember).filter_by(community_id=c.id, user_id=user.id).one_or_none()
    )
    my_role = my_membership.role if my_membership is not None else None
    my_request = (
        db.query(CommunityJoinRequest)
        .filter_by(community_id=c.id, user_id=user.id)
        .order_by(CommunityJoinRequest.requested_at.desc())
        .first()
    )
    my_status = my_request.status if my_request is not None else None
    return CommunityPreview(
        id=c.id,
        slug=c.slug,
        name=c.name,
        description=c.description,
        member_count=member_count,
        your_membership_role=my_role,
        your_join_request_status=my_status,
    )


@router.patch("/communities/{community_id}", response_model=CommunityRead)
def update_community_endpoint(
    community_id: uuid.UUID,
    request: CommunityUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> CommunityRead:
    try:
        c = community_svc.get_community_or_404(db, community_id)
        community_svc.update_community(
            db,
            owner_user=user,
            community=c,
            name=request.name,
            description=request.description,
        )
    except CommunityNotFound:
        raise HTTPException(status_code=404, detail="community not found") from None
    except NotACommunityMember:
        raise HTTPException(status_code=403, detail="must be a community owner") from None
    db.commit()
    db.refresh(c)
    return CommunityRead.model_validate(c)


@router.delete("/communities/{community_id}")
def delete_community_endpoint(
    community_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> dict:
    try:
        c = community_svc.get_community_or_404(db, community_id)
        community_svc.soft_delete_community(db, owner_user=user, community=c)
    except CommunityNotFound:
        raise HTTPException(status_code=404, detail="community not found") from None
    except NotACommunityMember:
        raise HTTPException(status_code=403, detail="must be a community owner") from None
    db.commit()
    return {"status": "deleted"}


@router.post("/communities/{community_id}/leave")
def leave_community_endpoint(
    community_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> dict:
    try:
        c = community_svc.get_community_or_404(db, community_id)
        community_svc.leave_community(db, user=user, community=c)
    except CommunityNotFound:
        raise HTTPException(status_code=404, detail="community not found") from None
    except NotACommunityMember:
        raise HTTPException(status_code=403, detail="not a member") from None
    except SoleOwnerCannotLeave:
        raise HTTPException(
            status_code=409,
            detail="sole owner — delete the community instead",
        ) from None
    db.commit()
    return {"status": "left"}


@router.post("/communities/{community_id}/join-requests", response_model=JoinRequestRead)
def request_to_join_endpoint(
    community_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> JoinRequestRead:
    try:
        c = community_svc.get_community_or_404(db, community_id)
        req = jr_svc.request_to_join(db, user=user, community=c)
    except CommunityNotFound:
        raise HTTPException(status_code=404, detail="community not found") from None
    except AlreadyAMember:
        raise HTTPException(status_code=409, detail="already a member") from None
    except AlreadyPending:
        raise HTTPException(status_code=409, detail="already have a pending request") from None
    db.commit()
    db.refresh(req)
    return JoinRequestRead.model_validate(req)


@router.post("/communities/{community_id}/join-requests/withdraw")
def withdraw_request_endpoint(
    community_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> dict:
    # Find the caller's own pending request for this community.
    req = (
        db.query(CommunityJoinRequest)
        .filter_by(community_id=community_id, user_id=user.id, status="pending")
        .one_or_none()
    )
    if req is None:
        raise HTTPException(status_code=404, detail="no pending request")
    try:
        jr_svc.withdraw_request(db, user=user, request=req)
    except (JoinRequestNotFound, AlreadyDecided) as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    db.commit()
    return {"status": "withdrawn"}


@router.get("/communities/{community_id}/join-requests", response_model=list[JoinRequestRead])
def list_join_requests_endpoint(
    community_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> list[JoinRequestRead]:
    try:
        c = community_svc.get_community_or_404(db, community_id)
        # Reuse the owner check from the service.
        community_svc._require_owner(db, user=user, community=c)
    except CommunityNotFound:
        raise HTTPException(status_code=404, detail="community not found") from None
    except NotACommunityMember:
        raise HTTPException(status_code=403, detail="must be a community owner") from None
    rows = jr_svc.list_pending_requests(db, community=c)
    return [JoinRequestRead.model_validate(r) for r in rows]


@router.post(
    "/communities/{community_id}/join-requests/{request_id}/approve",
    response_model=JoinRequestRead,
)
def approve_request_endpoint(
    community_id: uuid.UUID,
    request_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> JoinRequestRead:
    try:
        req = get_request_or_404(db, request_id)
        if req.community_id != community_id:
            raise JoinRequestNotFound(str(request_id))
        jr_svc.approve_request(db, owner_user=user, request=req)
    except JoinRequestNotFound:
        raise HTTPException(status_code=404, detail="join request not found") from None
    except NotACommunityMember:
        raise HTTPException(status_code=403, detail="must be a community owner") from None
    except AlreadyDecided:
        raise HTTPException(status_code=409, detail="already decided") from None
    db.commit()
    db.refresh(req)
    return JoinRequestRead.model_validate(req)


@router.post(
    "/communities/{community_id}/join-requests/{request_id}/decline",
    response_model=JoinRequestRead,
)
def decline_request_endpoint(
    community_id: uuid.UUID,
    request_id: uuid.UUID,
    request: JoinRequestDecideRequest,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> JoinRequestRead:
    try:
        req = get_request_or_404(db, request_id)
        if req.community_id != community_id:
            raise JoinRequestNotFound(str(request_id))
        jr_svc.decline_request(db, owner_user=user, request=req, note=request.note)
    except JoinRequestNotFound:
        raise HTTPException(status_code=404, detail="join request not found") from None
    except NotACommunityMember:
        raise HTTPException(status_code=403, detail="must be a community owner") from None
    except AlreadyDecided:
        raise HTTPException(status_code=409, detail="already decided") from None
    db.commit()
    db.refresh(req)
    return JoinRequestRead.model_validate(req)


# ---------------------------------------------------------------------------
# Discovery feed
# ---------------------------------------------------------------------------

@router.get("/feed", response_model=FeedResponse)
def feed_endpoint(
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    community_id: Annotated[uuid.UUID | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    radius_miles_max: Annotated[int | None, Query(ge=1, le=500)] = None,
    cursor: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> FeedResponse:
    """The discovery feed. Every row's visibility was decided by
    `listings_visible_to(...)` — there is no other path for cross-household reads.
    Newest-first ordering; pagination is offset-based (opaque cursor)."""
    q = listings_visible_to(db, viewer_household=household, viewer_user=user)
    # Order by listing recency (newest first).
    q = q.order_by(Listing.created_at.desc())

    if category is not None:
        q = q.join(CommunityItem, CommunityItem.id == Listing.item_id).filter(
            CommunityItem.category == category
        )

    rows: list[FeedRow] = []
    fetched = q.offset(cursor).limit(limit + 1).all()
    has_more = len(fetched) > limit
    for listing in fetched[:limit]:
        item = db.get(CommunityItem, listing.item_id)
        if item is None:
            continue
        owner_h = db.get(Household, item.household_id)
        distance = distance_for(household, owner_h) if owner_h else None
        # Optional caller-side max-distance cap on radius rows.
        if (
            distance is not None
            and radius_miles_max is not None
            and distance > radius_miles_max
        ):
            continue

        # Did this row match via a shared community?
        community_match = None
        if community_id is not None:
            # If the caller filtered to a specific community, the match IS that one.
            community_match = community_id
        else:
            shared_membership = (
                db.query(CommunityMember.community_id)
                .join(
                    ListingCommunity,
                    ListingCommunity.community_id == CommunityMember.community_id,
                )
                .filter(
                    ListingCommunity.listing_id == listing.id,
                    CommunityMember.user_id == user.id,
                )
                .first()
            )
            if shared_membership:
                community_match = shared_membership[0]

        rows.append(FeedRow(
            listing=_listing_read(db, listing),
            distance_miles=distance if listing.share_in_radius else None,
            matched_community_id=community_match,
        ))

    next_cursor = str(cursor + limit) if has_more else None
    # If caller filtered by community_id, narrow to listings actually in that community.
    if community_id is not None:
        rows = [
            r for r in rows
            if any(
                lc.community_id == community_id
                for lc in db.query(ListingCommunity).filter_by(
                    listing_id=(
                        uuid.UUID(r.listing.id)
                        if isinstance(r.listing.id, str)
                        else r.listing.id
                    ),
                ).all()
            )
        ]

    return FeedResponse(rows=rows, next_cursor=next_cursor)


# ---------------------------------------------------------------------------
# Household location
# ---------------------------------------------------------------------------


class _HouseholdLocationRequest(_BaseModel):
    lat: float
    lng: float
    share_radius_miles: int | None = None


@router.post("/household/location")
def set_household_location_endpoint(
    request: _HouseholdLocationRequest,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Update the active household's lat/lng (stored in metadata_).
    Only the household owner/member may set this (`viewer` cannot)."""
    from app.services.community.listings import NotHouseholdMember, _require_household_member
    try:
        _require_household_member(db, user=user, household=household)
    except NotHouseholdMember:
        raise HTTPException(status_code=403, detail="must be a household owner or member") from None
    md = dict(household.metadata_ or {})
    md["lat"] = float(request.lat)
    md["lng"] = float(request.lng)
    if request.share_radius_miles is not None:
        md["share_radius_miles"] = int(request.share_radius_miles)
    household.metadata_ = md
    db.flush()
    db.commit()
    return {"status": "set"}
