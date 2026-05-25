"""Community join-request service. The approval path is idempotent via a
conditional UPDATE: only a pending row transitions; concurrent approves race
safely (one wins, the rest see AlreadyDecided)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.community import (
    Community,
    CommunityJoinRequest,
    CommunityMember,
)
from app.models.core import AuditLog, User
from app.services.community.communities import _require_owner
from app.services.events import emit_event


class JoinRequestNotFound(Exception):
    pass


class AlreadyPending(Exception):
    pass


class AlreadyAMember(Exception):
    pass


class AlreadyDecided(Exception):
    """Request is no longer pending — already approved/declined/withdrawn."""


def _audit(db: Session, *, action: str, user_id, community_id, payload: dict | None = None) -> None:
    db.add(AuditLog(
        actor_user_id=user_id,
        action=action,
        target_type="community",
        target_id=community_id,
        payload=payload or {},
    ))
    db.flush()


def get_request_or_404(db: Session, request_id: uuid.UUID) -> CommunityJoinRequest:
    req = db.get(CommunityJoinRequest, request_id)
    if req is None:
        raise JoinRequestNotFound(str(request_id))
    return req


def request_to_join(
    db: Session, *, user: User, community: Community,
) -> CommunityJoinRequest:
    """Open a pending request. 409 if already a member or a pending request exists."""
    existing_member = (
        db.query(CommunityMember)
        .filter_by(community_id=community.id, user_id=user.id)
        .one_or_none()
    )
    if existing_member is not None:
        raise AlreadyAMember(f"user {user.id} is already a member of community {community.id}")

    req = CommunityJoinRequest(
        community_id=community.id, user_id=user.id, status="pending",
    )
    db.add(req)
    try:
        db.flush()
    except IntegrityError:
        # Partial unique index `ux_pending_per_user_per_community` was violated.
        db.rollback()
        raise AlreadyPending(str(community.id)) from None

    emit_event(
        db,
        event_type="community.join_request.requested",
        user_id=user.id,
        entity_type="community",
        entity_id=community.id,
    )
    return req


def withdraw_request(
    db: Session, *, user: User, request: CommunityJoinRequest,
) -> CommunityJoinRequest:
    """The requester withdraws their own pending request."""
    if request.user_id != user.id:
        raise JoinRequestNotFound(str(request.id))  # don't reveal someone else's request
    if request.status != "pending":
        raise AlreadyDecided(request.status)
    request.status = "withdrawn"
    request.decided_at = datetime.now(UTC)
    db.flush()
    return request


def approve_request(
    db: Session, *, owner_user: User, request: CommunityJoinRequest,
) -> CommunityMember:
    """Approve a pending request → create membership. Atomic + idempotent: a
    conditional UPDATE on `status='pending'` ensures concurrent approves are safe."""
    community = db.get(Community, request.community_id)
    if community is None or community.deleted_at is not None:
        raise JoinRequestNotFound(str(request.id))
    _require_owner(db, user=owner_user, community=community)

    now = datetime.now(UTC)
    result = db.execute(
        update(CommunityJoinRequest)
        .where(
            CommunityJoinRequest.id == request.id,
            CommunityJoinRequest.status == "pending",
        )
        .values(
            status="approved",
            decided_at=now,
            decided_by_user_id=owner_user.id,
        )
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise AlreadyDecided("approved-or-already-decided")

    # Create membership (idempotent against the unique constraint — if a race
    # somehow created it elsewhere, swallow and return the existing).
    existing = (
        db.query(CommunityMember)
        .filter_by(community_id=community.id, user_id=request.user_id)
        .one_or_none()
    )
    if existing is None:
        existing = CommunityMember(
            community_id=community.id, user_id=request.user_id, role="member",
        )
        db.add(existing)
        db.flush()

    emit_event(
        db,
        event_type="community.member.joined",
        user_id=request.user_id,
        entity_type="community",
        entity_id=community.id,
        payload={"approved_by_user_id": str(owner_user.id)},
    )
    emit_event(
        db,
        event_type="community.join_request.approved",
        user_id=owner_user.id,
        entity_type="community",
        entity_id=community.id,
        payload={"request_id": str(request.id), "joiner_user_id": str(request.user_id)},
    )
    _audit(db, action="community.join_request.approved", user_id=owner_user.id,
           community_id=community.id,
           payload={"request_id": str(request.id), "joiner_user_id": str(request.user_id)})
    return existing


def decline_request(
    db: Session, *, owner_user: User, request: CommunityJoinRequest, note: str | None = None,
) -> CommunityJoinRequest:
    community = db.get(Community, request.community_id)
    if community is None or community.deleted_at is not None:
        raise JoinRequestNotFound(str(request.id))
    _require_owner(db, user=owner_user, community=community)

    now = datetime.now(UTC)
    result = db.execute(
        update(CommunityJoinRequest)
        .where(
            CommunityJoinRequest.id == request.id,
            CommunityJoinRequest.status == "pending",
        )
        .values(
            status="declined",
            decided_at=now,
            decided_by_user_id=owner_user.id,
            decision_note=note,
        )
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise AlreadyDecided("declined-or-already-decided")

    db.refresh(request)
    emit_event(
        db,
        event_type="community.join_request.declined",
        user_id=owner_user.id,
        entity_type="community",
        entity_id=community.id,
        payload={"request_id": str(request.id)},
    )
    _audit(db, action="community.join_request.declined", user_id=owner_user.id,
           community_id=community.id,
           payload={"request_id": str(request.id), "note": note})
    return request


def list_pending_requests(
    db: Session, *, community: Community,
) -> list[CommunityJoinRequest]:
    return (
        db.query(CommunityJoinRequest)
        .filter(
            CommunityJoinRequest.community_id == community.id,
            CommunityJoinRequest.status == "pending",
        )
        .order_by(CommunityJoinRequest.requested_at)
        .all()
    )
