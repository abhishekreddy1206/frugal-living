"""/api/v1/admin/users — list/detail/role/active/lock/unlock."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.auth import CurrentModerator, CurrentUser
from app.db import get_db
from app.models.community import Listing
from app.models.core import HouseholdMember, User
from app.schemas.admin import (
    IsActivePatch,
    LockBody,
    ModerationReason,
    RolePatch,
    UserDetail,
    UserListRow,
)
from app.services.admin.users import change_role, lock_user, set_active, unlock_user
from app.services.auth.permissions import is_admin, is_at_least_moderator

router = APIRouter()


def _row(u: User) -> UserListRow:
    return UserListRow(
        id=u.id, email=u.email, display_name=u.display_name,
        role=u.role, is_active=u.is_active, locked_until=u.locked_until,
        created_at=u.created_at,
    )


@router.get("", response_model=list[UserListRow])
def list_users(
    _: CurrentModerator,
    db: Session = Depends(get_db),
    q: str | None = Query(None, description="case-insensitive substring on email"),
    role: str | None = Query(None),
    active: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    query = db.query(User)
    if q:
        query = query.filter(User.email.ilike(f"%{q}%"))
    if role:
        query = query.filter(User.role == role)
    if active is not None:
        query = query.filter(User.is_active.is_(active))
    rows = query.order_by(User.created_at.desc()).offset(offset).limit(limit).all()
    return [_row(u) for u in rows]


@router.get("/{user_id}", response_model=UserDetail)
def get_user(
    user_id: UUID, _: CurrentModerator, db: Session = Depends(get_db),
):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "user not found")
    memberships = db.query(HouseholdMember).filter_by(user_id=u.id).all()
    listing_count = (
        db.query(Listing)
        .filter(Listing.created_by_user_id == u.id, Listing.deleted_at.is_(None))
        .count()
    )
    return UserDetail(
        **_row(u).model_dump(),
        household_memberships=[
            {"household_id": str(m.household_id), "role": m.role}
            for m in memberships
        ],
        listing_count=listing_count,
    )


@router.patch("/{user_id}", response_model=UserListRow)
def patch_user(
    user_id: UUID,
    body: Annotated[dict, Body(...)],
    user: CurrentUser,  # use the base, then branch on body shape + role
    db: Session = Depends(get_db),
):
    """Two body shapes (cannot be combined — `role` takes precedence if both keys appear):
      { role: "user"|"moderator"|"admin" }            — admin only
      { is_active: bool, reason: str }                — admin OR moderator

    TODO: replace the dual-body dict pattern with FastAPI's RequestModel/oneOf
    once that gives better OpenAPI fidelity. For now clients see a generic dict.
    """
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "user not found")

    if "role" in body:
        if not is_admin(user):
            raise HTTPException(403, "admin required to change role")
        try:
            parsed_role = RolePatch(**body)
        except ValidationError as exc:
            raise HTTPException(422, detail=exc.errors()) from exc
        change_role(db, target=target, new_role=parsed_role.role, actor=user)
        db.commit()
        return _row(target)

    if "is_active" in body:
        if not is_at_least_moderator(user):
            raise HTTPException(403, "moderator required")
        try:
            parsed_active = IsActivePatch(**body)
        except ValidationError as exc:
            raise HTTPException(422, detail=exc.errors()) from exc
        set_active(
            db, target=target, is_active=parsed_active.is_active,
            reason=parsed_active.reason, actor=user,
        )
        db.commit()
        return _row(target)

    raise HTTPException(422, "body must include 'role' or 'is_active'")


@router.post("/{user_id}/lock", status_code=status.HTTP_204_NO_CONTENT)
def lock(
    user_id: UUID, body: LockBody,
    actor: CurrentModerator, db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "user not found")
    lock_user(db, target=target, hours=body.hours, reason=body.reason, actor=actor)
    db.commit()


@router.post("/{user_id}/unlock", status_code=status.HTTP_204_NO_CONTENT)
def unlock(
    user_id: UUID, body: ModerationReason,
    actor: CurrentModerator, db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "user not found")
    unlock_user(db, target=target, reason=body.reason, actor=actor)
    db.commit()
