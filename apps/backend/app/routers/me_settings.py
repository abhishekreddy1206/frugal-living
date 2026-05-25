"""Self-service settings: /me/settings/* and /households/{id}/settings/*."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.db import get_db
from app.models.core import Household, HouseholdMember
from app.schemas.settings import SettingValueRead, SettingWrite
from app.services.settings.registry import SETTING_REGISTRY
from app.services.settings.resolver import clear_setting, get_setting, set_setting

router = APIRouter()


# --- /me/settings ---

@router.get("/me/settings", response_model=list[SettingValueRead])
def list_my_settings(user: CurrentUser, db: Session = Depends(get_db)):
    """Return every user-scoped setting with the resolved value for *this user*."""
    out = []
    for key, spec in SETTING_REGISTRY.items():
        if "user" not in spec.scopes:
            continue
        out.append(SettingValueRead(
            key=key, value=get_setting(db, key, user=user),
            scope="user", scope_id=user.id,
        ))
    return out


@router.put("/me/settings/{key}", status_code=status.HTTP_204_NO_CONTENT)
def set_my_setting(
    key: str, body: SettingWrite, user: CurrentUser, db: Session = Depends(get_db),
):
    if key not in SETTING_REGISTRY:
        raise HTTPException(status_code=404, detail="unknown setting key")
    try:
        set_setting(db, key, body.value, scope="user", scope_id=user.id, actor=user)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    db.commit()


@router.delete("/me/settings/{key}", status_code=status.HTTP_204_NO_CONTENT)
def clear_my_setting(key: str, user: CurrentUser, db: Session = Depends(get_db)):
    if key not in SETTING_REGISTRY:
        raise HTTPException(status_code=404, detail="unknown setting key")
    clear_setting(db, key, scope="user", scope_id=user.id, actor=user)
    db.commit()


# --- /households/{hid}/settings ---

def _require_member(db: Session, user_id, household_id) -> HouseholdMember:
    m = (
        db.query(HouseholdMember)
        .filter_by(user_id=user_id, household_id=household_id)
        .one_or_none()
    )
    if m is None:
        raise HTTPException(status_code=403, detail="not a member of this household")
    return m


def _require_owner(db: Session, user_id, household_id) -> None:
    m = _require_member(db, user_id, household_id)
    if m.role != "owner":
        raise HTTPException(status_code=403, detail="household owner role required")


@router.get("/households/{hid}/settings", response_model=list[SettingValueRead])
def list_household_settings(
    hid: UUID, user: CurrentUser, db: Session = Depends(get_db),
):
    _require_member(db, user.id, hid)
    hh = db.get(Household, hid)
    out = []
    for key, spec in SETTING_REGISTRY.items():
        if "household" not in spec.scopes:
            continue
        out.append(SettingValueRead(
            key=key, value=get_setting(db, key, household=hh),
            scope="household", scope_id=hid,
        ))
    return out


@router.put("/households/{hid}/settings/{key}", status_code=status.HTTP_204_NO_CONTENT)
def set_household_setting(
    hid: UUID, key: str, body: SettingWrite,
    user: CurrentUser, db: Session = Depends(get_db),
):
    if key not in SETTING_REGISTRY:
        raise HTTPException(status_code=404, detail="unknown setting key")
    _require_owner(db, user.id, hid)
    try:
        set_setting(db, key, body.value, scope="household", scope_id=hid, actor=user)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    db.commit()


@router.delete("/households/{hid}/settings/{key}", status_code=status.HTTP_204_NO_CONTENT)
def clear_household_setting(
    hid: UUID, key: str, user: CurrentUser, db: Session = Depends(get_db),
):
    if key not in SETTING_REGISTRY:
        raise HTTPException(status_code=404, detail="unknown setting key")
    _require_owner(db, user.id, hid)
    clear_setting(db, key, scope="household", scope_id=hid, actor=user)
    db.commit()
