"""Public runtime configuration. No auth. Returns whitelisted globals only."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.core import AppSettingKv
from app.services.settings.registry import SETTING_REGISTRY

router = APIRouter()


@router.get("", response_model=dict[str, Any])
def get_runtime_config(db: Session = Depends(get_db)):
    out: dict[str, Any] = {}
    for key, spec in SETTING_REGISTRY.items():
        if not spec.public:
            continue
        row = db.get(AppSettingKv, key)
        out[key] = row.value if row is not None else spec.default
    return out
