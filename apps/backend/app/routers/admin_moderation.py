"""/api/v1/admin/{communities,listings} — moderator-grade moderation surface."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import CurrentModerator
from app.db import get_db
from app.models.community import (
    Community,
    CommunityItem,
    CommunityMember,
    Listing,
    ListingCommunity,
)
from app.schemas.admin import ModerationReason
from app.services.admin.moderation import (
    restore_community,
    restore_listing,
    take_down_community,
    take_down_listing,
)

router = APIRouter()


# --- Communities ---

@router.get("/communities")
def list_communities(
    _: CurrentModerator,
    db: Session = Depends(get_db),
    q: str | None = Query(None),
    include_deleted: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    query = db.query(Community)
    if not include_deleted:
        query = query.filter(Community.deleted_at.is_(None))
    if q:
        query = query.filter(Community.name.ilike(f"%{q}%"))
    rows = query.order_by(Community.created_at.desc()).offset(offset).limit(limit).all()
    return [
        {
            "id": str(c.id), "name": c.name, "slug": c.slug,
            "created_at": c.created_at.isoformat(),
            "deleted_at": c.deleted_at.isoformat() if c.deleted_at else None,
            "created_by_user_id": str(c.created_by_user_id),
        }
        for c in rows
    ]


@router.get("/communities/{cid}")
def get_community(cid: UUID, _: CurrentModerator, db: Session = Depends(get_db)):
    c = db.get(Community, cid)
    if c is None:
        raise HTTPException(404, "community not found")
    member_count = db.query(CommunityMember).filter_by(community_id=cid).count()
    listing_count = db.query(ListingCommunity).filter_by(community_id=cid).count()
    return {
        "id": str(c.id), "name": c.name, "slug": c.slug,
        "created_at": c.created_at.isoformat(),
        "deleted_at": c.deleted_at.isoformat() if c.deleted_at else None,
        "created_by_user_id": str(c.created_by_user_id),
        "member_count": member_count,
        "listing_count": listing_count,
    }


@router.post("/communities/{cid}/take-down", status_code=status.HTTP_204_NO_CONTENT)
def take_down_community_endpoint(
    cid: UUID, body: ModerationReason,
    actor: CurrentModerator, db: Session = Depends(get_db),
):
    c = db.get(Community, cid)
    if c is None:
        raise HTTPException(404, "community not found")
    take_down_community(db, community=c, reason=body.reason, actor=actor)
    db.commit()


@router.post("/communities/{cid}/restore", status_code=status.HTTP_204_NO_CONTENT)
def restore_community_endpoint(
    cid: UUID, body: ModerationReason,
    actor: CurrentModerator, db: Session = Depends(get_db),
):
    c = db.get(Community, cid)
    if c is None:
        raise HTTPException(404, "community not found")
    restore_community(db, community=c, reason=body.reason, actor=actor)
    db.commit()


# --- Listings ---

@router.get("/listings")
def list_listings(
    _: CurrentModerator,
    db: Session = Depends(get_db),
    q: str | None = Query(None),
    availability_status: str | None = Query(None),
    include_deleted: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    query = db.query(Listing)
    if not include_deleted:
        query = query.filter(Listing.deleted_at.is_(None))
    if availability_status:
        query = query.filter(Listing.availability_status == availability_status)
    if q:
        # Search by item name via join
        query = query.join(CommunityItem, Listing.item_id == CommunityItem.id)
        query = query.filter(CommunityItem.name.ilike(f"%{q}%"))
    rows = query.order_by(Listing.created_at.desc()).offset(offset).limit(limit).all()
    return [
        {
            "id": str(row.id),
            "item_id": str(row.item_id),
            "availability_status": row.availability_status,
            "created_at": row.created_at.isoformat(),
            "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
        }
        for row in rows
    ]


@router.get("/listings/{lid}")
def get_listing(lid: UUID, _: CurrentModerator, db: Session = Depends(get_db)):
    listing = db.get(Listing, lid)
    if listing is None:
        raise HTTPException(404, "listing not found")
    communities = [
        str(lc.community_id)
        for lc in db.query(ListingCommunity).filter_by(listing_id=lid).all()
    ]
    return {
        "id": str(listing.id),
        "item_id": str(listing.item_id),
        "availability_status": listing.availability_status,
        "allowed_exchange_types": listing.allowed_exchange_types,
        "quantity_available": listing.quantity_available,
        "description": listing.description_override,
        "created_at": listing.created_at.isoformat(),
        "deleted_at": listing.deleted_at.isoformat() if listing.deleted_at else None,
        "shared_with_communities": communities,
    }


@router.post("/listings/{lid}/take-down", status_code=status.HTTP_204_NO_CONTENT)
def take_down_listing_endpoint(
    lid: UUID, body: ModerationReason,
    actor: CurrentModerator, db: Session = Depends(get_db),
):
    listing = db.get(Listing, lid)
    if listing is None:
        raise HTTPException(404, "listing not found")
    take_down_listing(db, listing=listing, reason=body.reason, actor=actor)
    db.commit()


@router.post("/listings/{lid}/restore", status_code=status.HTTP_204_NO_CONTENT)
def restore_listing_endpoint(
    lid: UUID, body: ModerationReason,
    actor: CurrentModerator, db: Session = Depends(get_db),
):
    listing = db.get(Listing, lid)
    if listing is None:
        raise HTTPException(404, "listing not found")
    restore_listing(db, listing=listing, reason=body.reason, actor=actor)
    db.commit()
