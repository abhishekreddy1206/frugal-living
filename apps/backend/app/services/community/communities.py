"""Communities service — create / fetch / soft-delete / leave."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.community import Community, CommunityMember
from app.models.core import AuditLog, User
from app.services.events import emit_event


class CommunityNotFound(Exception):
    """Community id or slug not found (or soft-deleted)."""


class CommunitySlugTaken(Exception):
    """A community with that slug already exists."""


class NotACommunityMember(Exception):
    """User is not a member (or not an owner) of the community."""


class SoleOwnerCannotLeave(Exception):
    """Owner may not leave when they are the only owner — soft-delete instead."""


def _audit(db: Session, *, action: str, user_id, community_id, payload: dict | None = None) -> None:
    db.add(
        AuditLog(
            actor_user_id=user_id,
            action=action,
            target_type="community",
            target_id=community_id,
            payload=payload or {},
        )
    )
    db.flush()


def get_community_by_slug(db: Session, slug: str) -> Community | None:
    return (
        db.query(Community)
        .filter(Community.slug == slug, Community.deleted_at.is_(None))
        .one_or_none()
    )


def get_community_or_404(db: Session, community_id: uuid.UUID) -> Community:
    c = db.get(Community, community_id)
    if c is None or c.deleted_at is not None:
        raise CommunityNotFound(str(community_id))
    return c


def _require_owner(db: Session, *, user: User, community: Community) -> CommunityMember:
    member = (
        db.query(CommunityMember)
        .filter_by(community_id=community.id, user_id=user.id)
        .one_or_none()
    )
    if member is None or member.role != "owner":
        raise NotACommunityMember(f"user {user.id} is not an owner of community {community.id}")
    return member


def create_community(
    db: Session,
    *,
    creator_user: User,
    slug: str,
    name: str,
    description: str | None = None,
) -> Community:
    """Create a community, add creator as owner, emit event + audit row."""
    c = Community(
        slug=slug.lower(),
        name=name,
        description=description,
        created_by_user_id=creator_user.id,
    )
    db.add(c)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise CommunitySlugTaken(slug) from None

    db.add(CommunityMember(community_id=c.id, user_id=creator_user.id, role="owner"))
    db.flush()

    emit_event(
        db,
        event_type="community.community.created",
        user_id=creator_user.id,
        entity_type="community",
        entity_id=c.id,
        payload={"slug": c.slug, "name": c.name},
    )
    _audit(
        db,
        action="community.community.created",
        user_id=creator_user.id,
        community_id=c.id,
        payload={"slug": c.slug},
    )
    return c


def update_community(
    db: Session,
    *,
    owner_user: User,
    community: Community,
    name: str | None = None,
    description: str | None = None,
) -> Community:
    _require_owner(db, user=owner_user, community=community)
    changed: dict[str, object] = {}
    if name is not None:
        community.name = name
        changed["name"] = name
    if description is not None:
        community.description = description
        changed["description"] = description
    if changed:
        db.flush()
        _audit(
            db,
            action="community.community.updated",
            user_id=owner_user.id,
            community_id=community.id,
            payload={"changed": changed},
        )
    return community


def soft_delete_community(db: Session, *, owner_user: User, community: Community) -> None:
    _require_owner(db, user=owner_user, community=community)
    community.deleted_at = datetime.now(UTC)
    db.flush()
    emit_event(
        db,
        event_type="community.community.deleted",
        user_id=owner_user.id,
        entity_type="community",
        entity_id=community.id,
        payload={"slug": community.slug},
    )
    _audit(
        db,
        action="community.community.deleted",
        user_id=owner_user.id,
        community_id=community.id,
    )


def leave_community(db: Session, *, user: User, community: Community) -> None:
    member = (
        db.query(CommunityMember)
        .filter_by(community_id=community.id, user_id=user.id)
        .one_or_none()
    )
    if member is None:
        raise NotACommunityMember(f"user {user.id} is not a member of community {community.id}")
    if member.role == "owner":
        # If they are the *only* owner, refuse — owner must soft-delete the community.
        other_owners = (
            db.query(CommunityMember)
            .filter(
                CommunityMember.community_id == community.id,
                CommunityMember.role == "owner",
                CommunityMember.user_id != user.id,
            )
            .count()
        )
        if other_owners == 0:
            raise SoleOwnerCannotLeave(str(community.id))
    db.delete(member)
    db.flush()
    emit_event(
        db,
        event_type="community.member.left",
        user_id=user.id,
        entity_type="community",
        entity_id=community.id,
    )


def list_my_communities(db: Session, *, user: User) -> list[tuple[Community, CommunityMember]]:
    """Communities the user currently belongs to (with role)."""
    rows = (
        db.query(Community, CommunityMember)
        .join(CommunityMember, CommunityMember.community_id == Community.id)
        .filter(
            CommunityMember.user_id == user.id,
            Community.deleted_at.is_(None),
        )
        .order_by(Community.name)
        .all()
    )
    # SQLAlchemy 2.x returns Row[...] objects; convert to plain tuples for the type annotation.
    return [(c, m) for c, m in rows]
