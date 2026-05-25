"""Admin endpoints for feature flags + per-household / per-user overrides."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import CurrentAdmin
from app.db import get_db
from app.models.core import (
    AuditLog,
    FeatureFlag,
    FeatureFlagOverride,
)
from app.schemas.flags import (
    FeatureFlagCreate,
    FeatureFlagPatch,
    FeatureFlagRead,
    OverrideWrite,
)
from app.services.flags.admin import (
    clear_household_override,
    clear_user_override,
    set_household_override,
    set_user_override,
)

router = APIRouter()


def _flag_or_404(db: Session, key: str) -> FeatureFlag:
    f = (
        db.query(FeatureFlag)
        .filter(FeatureFlag.key == key, FeatureFlag.deleted_at.is_(None))
        .one_or_none()
    )
    if f is None:
        raise HTTPException(status_code=404, detail="flag not found")
    return f


def _read(db: Session, f: FeatureFlag) -> FeatureFlagRead:
    hh_count = (
        db.query(FeatureFlagOverride)
        .filter_by(flag_key=f.key)
        .filter(FeatureFlagOverride.household_id.isnot(None))
        .count()
    )
    u_count = (
        db.query(FeatureFlagOverride)
        .filter_by(flag_key=f.key)
        .filter(FeatureFlagOverride.user_id.isnot(None))
        .count()
    )
    return FeatureFlagRead(
        key=f.key, description=f.description,
        enabled_globally=f.enabled_globally, rollout_percent=f.rollout_percent,
        household_override_count=hh_count, user_override_count=u_count,
    )


@router.get("", response_model=list[FeatureFlagRead])
def list_flags(_: CurrentAdmin, db: Session = Depends(get_db)):
    flags = (
        db.query(FeatureFlag)
        .filter(FeatureFlag.deleted_at.is_(None))
        .order_by(FeatureFlag.key)
        .all()
    )
    return [_read(db, f) for f in flags]


@router.post("", response_model=FeatureFlagRead, status_code=status.HTTP_201_CREATED)
def create_flag(body: FeatureFlagCreate, user: CurrentAdmin, db: Session = Depends(get_db)):
    f = FeatureFlag(
        key=body.key, description=body.description,
        enabled_globally=body.enabled_globally, rollout_percent=body.rollout_percent,
    )
    db.add(f)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="flag key already exists") from None
    db.add(AuditLog(
        actor_user_id=user.id, action="admin.flag.created",
        target_type="feature_flag", target_id=None,
        payload={
            "key": body.key,
            "enabled_globally": body.enabled_globally,
            "rollout_percent": body.rollout_percent,
        },
    ))
    db.commit()
    return _read(db, f)


@router.get("/{key}")
def get_flag(key: str, _: CurrentAdmin, db: Session = Depends(get_db)):
    f = _flag_or_404(db, key)
    overrides = db.query(FeatureFlagOverride).filter_by(flag_key=key).all()
    return {
        **_read(db, f).model_dump(),
        "household_overrides": [
            {"id": str(o.id), "household_id": str(o.household_id), "enabled": o.enabled}
            for o in overrides if o.household_id is not None
        ],
        "user_overrides": [
            {"id": str(o.id), "user_id": str(o.user_id), "enabled": o.enabled}
            for o in overrides if o.user_id is not None
        ],
    }


@router.patch("/{key}", response_model=FeatureFlagRead)
def patch_flag(
    key: str, body: FeatureFlagPatch, user: CurrentAdmin, db: Session = Depends(get_db),
):
    f = _flag_or_404(db, key)
    changes: dict = {}
    if body.description is not None:
        f.description = body.description
        changes["description"] = body.description
    if body.enabled_globally is not None:
        f.enabled_globally = body.enabled_globally
        changes["enabled_globally"] = body.enabled_globally
    if body.rollout_percent is not None:
        f.rollout_percent = body.rollout_percent
        changes["rollout_percent"] = body.rollout_percent
    if changes:
        db.add(AuditLog(
            actor_user_id=user.id, action="admin.flag.updated",
            target_type="feature_flag", target_id=None,
            payload={"key": key, **changes},
        ))
        db.commit()
    return _read(db, f)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_flag(key: str, user: CurrentAdmin, db: Session = Depends(get_db)):
    f = _flag_or_404(db, key)
    f.deleted_at = datetime.now(UTC)
    db.add(AuditLog(
        actor_user_id=user.id, action="admin.flag.deleted",
        target_type="feature_flag", target_id=None,
        payload={"key": key},
    ))
    db.commit()


@router.put("/{key}/household/{hid}", status_code=status.HTTP_204_NO_CONTENT)
def put_household_override(
    key: str, hid: UUID, body: OverrideWrite,
    user: CurrentAdmin, db: Session = Depends(get_db),
):
    _flag_or_404(db, key)
    set_household_override(db, flag_key=key, household_id=hid, enabled=body.enabled, actor=user)
    db.commit()


@router.delete("/{key}/household/{hid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_household_override(
    key: str, hid: UUID, user: CurrentAdmin, db: Session = Depends(get_db),
):
    clear_household_override(db, flag_key=key, household_id=hid, actor=user)
    db.commit()


@router.put("/{key}/user/{uid}", status_code=status.HTTP_204_NO_CONTENT)
def put_user_override(
    key: str, uid: UUID, body: OverrideWrite,
    user: CurrentAdmin, db: Session = Depends(get_db),
):
    _flag_or_404(db, key)
    set_user_override(db, flag_key=key, user_id=uid, enabled=body.enabled, actor=user)
    db.commit()


@router.delete("/{key}/user/{uid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user_override(
    key: str, uid: UUID, user: CurrentAdmin, db: Session = Depends(get_db),
):
    clear_user_override(db, flag_key=key, user_id=uid, actor=user)
    db.commit()
