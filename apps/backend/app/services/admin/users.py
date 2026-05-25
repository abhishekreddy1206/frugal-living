"""Service helpers for admin user-management endpoints."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session as DbSession

from app.models.core import AuditLog, Event, User
from app.services.auth.permissions import assert_not_last_admin


def change_role(db: DbSession, *, target: User, new_role: str, actor: User) -> None:
    if new_role == target.role:
        return
    if target.role == "admin" and new_role != "admin":
        assert_not_last_admin(db, target)
    old = target.role
    target.role = new_role
    db.add(AuditLog(
        actor_user_id=actor.id, action="admin.user.role_changed",
        target_type="user", target_id=target.id,
        payload={"from": old, "to": new_role},
    ))
    db.add(Event(
        user_id=actor.id, event_type="admin.user.role_changed",
        entity_type="user", entity_id=target.id,
        payload={"from": old, "to": new_role},
    ))


def set_active(db: DbSession, *, target: User, is_active: bool, reason: str, actor: User) -> None:
    if is_active == target.is_active:
        return
    if not is_active and target.role == "admin":
        assert_not_last_admin(db, target)
    target.is_active = is_active
    action = "admin.user.activated" if is_active else "admin.user.deactivated"
    db.add(AuditLog(
        actor_user_id=actor.id, action=action,
        target_type="user", target_id=target.id,
        payload={"reason": reason},
    ))
    db.add(Event(
        user_id=actor.id, event_type=action,
        entity_type="user", entity_id=target.id,
        payload={"reason": reason},
    ))


def lock_user(db: DbSession, *, target: User, hours: int, reason: str, actor: User) -> None:
    target.locked_until = datetime.now(UTC) + timedelta(hours=hours)
    db.add(AuditLog(
        actor_user_id=actor.id, action="admin.user.locked",
        target_type="user", target_id=target.id,
        payload={"reason": reason, "hours": hours},
    ))
    db.add(Event(
        user_id=actor.id, event_type="admin.user.locked",
        entity_type="user", entity_id=target.id,
        payload={"reason": reason, "hours": hours},
    ))


def unlock_user(db: DbSession, *, target: User, reason: str, actor: User) -> None:
    target.locked_until = None
    db.add(AuditLog(
        actor_user_id=actor.id, action="admin.user.unlocked",
        target_type="user", target_id=target.id,
        payload={"reason": reason},
    ))
    db.add(Event(
        user_id=actor.id, event_type="admin.user.unlocked",
        entity_type="user", entity_id=target.id,
        payload={"reason": reason},
    ))
