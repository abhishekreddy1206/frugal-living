"""Service helpers for moderating communities and listings."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session as DbSession

from app.models.community import Community, Listing
from app.models.core import AuditLog, Event, User


def take_down_community(db: DbSession, *, community: Community, reason: str, actor: User) -> None:
    if community.deleted_at is None:
        community.deleted_at = datetime.now(UTC)
    db.add(AuditLog(
        actor_user_id=actor.id, action="admin.community.taken_down",
        target_type="community", target_id=community.id,
        payload={"reason": reason},
    ))
    db.add(Event(
        user_id=actor.id, event_type="admin.community.taken_down",
        entity_type="community", entity_id=community.id,
        payload={"reason": reason},
    ))


def restore_community(db: DbSession, *, community: Community, reason: str, actor: User) -> None:
    community.deleted_at = None
    db.add(AuditLog(
        actor_user_id=actor.id, action="admin.community.restored",
        target_type="community", target_id=community.id,
        payload={"reason": reason},
    ))
    db.add(Event(
        user_id=actor.id, event_type="admin.community.restored",
        entity_type="community", entity_id=community.id,
        payload={"reason": reason},
    ))


def take_down_listing(db: DbSession, *, listing: Listing, reason: str, actor: User) -> None:
    if listing.deleted_at is None:
        listing.deleted_at = datetime.now(UTC)
    listing.availability_status = "removed"
    db.add(AuditLog(
        actor_user_id=actor.id, action="admin.listing.taken_down",
        target_type="listing", target_id=listing.id,
        payload={"reason": reason},
    ))
    db.add(Event(
        user_id=actor.id, event_type="admin.listing.taken_down",
        entity_type="listing", entity_id=listing.id,
        payload={"reason": reason},
    ))


def restore_listing(db: DbSession, *, listing: Listing, reason: str, actor: User) -> None:
    listing.deleted_at = None
    listing.availability_status = "available"
    db.add(AuditLog(
        actor_user_id=actor.id, action="admin.listing.restored",
        target_type="listing", target_id=listing.id,
        payload={"reason": reason},
    ))
    db.add(Event(
        user_id=actor.id, event_type="admin.listing.restored",
        entity_type="listing", entity_id=listing.id,
        payload={"reason": reason},
    ))
