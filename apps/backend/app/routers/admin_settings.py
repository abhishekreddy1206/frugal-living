"""Admin endpoints for app settings (3-layer)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import CurrentAdmin
from app.db import get_db
from app.models.core import AppSettingKv, HouseholdSetting, UserSetting
from app.schemas.settings import GlobalSettingRow, RegistryEntry, SettingDetail, SettingWrite
from app.services.settings.registry import SETTING_REGISTRY
from app.services.settings.resolver import clear_setting, set_setting

router = APIRouter()


def _registry_entry(key: str) -> RegistryEntry:
    spec = SETTING_REGISTRY[key]
    return RegistryEntry(
        key=key, type=spec.type.__name__, default=spec.default,
        scopes=list(spec.scopes), description=spec.description, public=spec.public,
    )


def _require_known(key: str) -> None:
    if key not in SETTING_REGISTRY:
        raise HTTPException(status_code=404, detail=f"unknown setting key: {key}")


@router.get("", response_model=list[GlobalSettingRow])
def list_settings(_: CurrentAdmin, db: Session = Depends(get_db)):
    """List every registry setting with current global value + override counts."""
    rows = []
    # One query each for override counts (small N of registry keys)
    for key, spec in SETTING_REGISTRY.items():
        gl = db.get(AppSettingKv, key)
        hh_count = db.query(HouseholdSetting).filter_by(key=key).count()
        u_count = db.query(UserSetting).filter_by(key=key).count()
        rows.append(GlobalSettingRow(
            key=key,
            spec=_registry_entry(key),
            current_global=gl.value if gl is not None else spec.default,
            has_global_override=gl is not None,
            household_override_count=hh_count,
            user_override_count=u_count,
        ))
    return rows


@router.get("/registry", response_model=dict[str, RegistryEntry])
def get_registry(_: CurrentAdmin):
    return {k: _registry_entry(k) for k in SETTING_REGISTRY}


@router.get("/{key}", response_model=SettingDetail)
def get_setting_detail(key: str, _: CurrentAdmin, db: Session = Depends(get_db)):
    _require_known(key)
    spec = SETTING_REGISTRY[key]
    gl = db.get(AppSettingKv, key)
    hh = db.query(HouseholdSetting).filter_by(key=key).all()
    us = db.query(UserSetting).filter_by(key=key).all()
    return SettingDetail(
        key=key,
        spec=_registry_entry(key),
        current_global=gl.value if gl is not None else spec.default,
        has_global_override=gl is not None,
        household_overrides=[
            {
                "household_id": str(r.household_id),
                "value": r.value,
                "updated_at": r.updated_at.isoformat(),
            }
            for r in hh
        ],
        user_overrides=[
            {
                "user_id": str(r.user_id),
                "value": r.value,
                "updated_at": r.updated_at.isoformat(),
            }
            for r in us
        ],
    )


@router.put("/{key}", status_code=status.HTTP_204_NO_CONTENT)
def set_global(key: str, body: SettingWrite, user: CurrentAdmin, db: Session = Depends(get_db)):
    _require_known(key)
    try:
        set_setting(db, key, body.value, scope="global", scope_id=None, actor=user)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    db.commit()


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
def clear_global(key: str, user: CurrentAdmin, db: Session = Depends(get_db)):
    _require_known(key)
    clear_setting(db, key, scope="global", scope_id=None, actor=user)
    db.commit()


@router.put("/{key}/household/{hid}", status_code=status.HTTP_204_NO_CONTENT)
def set_household_override(
    key: str, hid: UUID, body: SettingWrite,
    user: CurrentAdmin, db: Session = Depends(get_db),
):
    _require_known(key)
    try:
        set_setting(db, key, body.value, scope="household", scope_id=hid, actor=user)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    db.commit()


@router.delete("/{key}/household/{hid}", status_code=status.HTTP_204_NO_CONTENT)
def clear_household_override(
    key: str, hid: UUID, user: CurrentAdmin, db: Session = Depends(get_db),
):
    _require_known(key)
    clear_setting(db, key, scope="household", scope_id=hid, actor=user)
    db.commit()


@router.put("/{key}/user/{uid}", status_code=status.HTTP_204_NO_CONTENT)
def set_user_override(
    key: str, uid: UUID, body: SettingWrite,
    user: CurrentAdmin, db: Session = Depends(get_db),
):
    _require_known(key)
    try:
        set_setting(db, key, body.value, scope="user", scope_id=uid, actor=user)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    db.commit()


@router.delete("/{key}/user/{uid}", status_code=status.HTTP_204_NO_CONTENT)
def clear_user_override(
    key: str, uid: UUID, user: CurrentAdmin, db: Session = Depends(get_db),
):
    _require_known(key)
    clear_setting(db, key, scope="user", scope_id=uid, actor=user)
    db.commit()
