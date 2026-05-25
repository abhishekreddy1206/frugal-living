"""Read-only audit log access for admins and moderators."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import CurrentModerator
from app.db import get_db
from app.models.core import AuditLog

router = APIRouter()


@router.get("/audit-log")
def list_audit_log(
    _: CurrentModerator,
    db: Session = Depends(get_db),
    actor_user_id: UUID | None = Query(None),
    action: str | None = Query(None),
    action_prefix: str | None = Query(None),
    target_type: str | None = Query(None),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    q = db.query(AuditLog)
    if actor_user_id is not None:
        q = q.filter(AuditLog.actor_user_id == actor_user_id)
    if action is not None:
        q = q.filter(AuditLog.action == action)
    if action_prefix is not None:
        q = q.filter(AuditLog.action.startswith(action_prefix))
    if target_type is not None:
        q = q.filter(AuditLog.target_type == target_type)
    if since is not None:
        q = q.filter(AuditLog.created_at >= since)
    if until is not None:
        q = q.filter(AuditLog.created_at < until)
    rows = q.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()
    return [
        {
            "id": str(r.id),
            "actor_user_id": str(r.actor_user_id) if r.actor_user_id else None,
            "action": r.action,
            "target_type": r.target_type,
            "target_id": str(r.target_id) if r.target_id else None,
            "payload": r.payload,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
