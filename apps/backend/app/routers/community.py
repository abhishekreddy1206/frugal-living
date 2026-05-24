"""Tier B — community routes. Phase 1: household inventory."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import CurrentHousehold, CurrentUser
from app.db import get_db
from app.models.community import CommunityItem, CommunityJoinRequest, CommunityMember
from app.schemas.community import (
    CommunityCreate,
    CommunityMembershipRead,
    CommunityPreview,
    CommunityRead,
    CommunityUpdate,
    ItemCaptureRequest,
    ItemCaptureResponse,
    ItemCreate,
    ItemRead,
    ItemUpdate,
    MyCommunitiesResponse,
)
from app.services.community import communities as community_svc
from app.services.community import items as items_service
from app.services.community.communities import (
    CommunityNotFound,
    CommunitySlugTaken,
    NotACommunityMember,
    SoleOwnerCannotLeave,
)
from app.services.community.items import CommunityItemNotFound
from app.services.llm import extract_items_from_image

router = APIRouter()


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
