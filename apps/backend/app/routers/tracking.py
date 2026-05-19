"""Tracking — savings dashboard, streaks, badges."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import CurrentHousehold, CurrentUser
from app.db import get_db
from app.models.tracking import BadgeAward, BadgeDefinition
from app.schemas.tracking import BadgeAwardRead, StreakRead
from app.services.streaks import evaluate_badges, recompute_streaks

router = APIRouter()


@router.get("/streaks", response_model=list[StreakRead])
def list_streaks(
    household: CurrentHousehold,
    db: Annotated[Session, Depends(get_db)],
) -> list[StreakRead]:
    """Recompute and return all streak kinds for the current household."""
    streaks = recompute_streaks(db, household)
    db.commit()
    return [StreakRead.model_validate(s) for s in streaks]


@router.get("/badges", response_model=list[BadgeAwardRead])
def list_badges(
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> list[BadgeAwardRead]:
    """Evaluate-then-list badges. Evaluation awards any newly-earned badges."""
    evaluate_badges(db, household, user.id)
    db.commit()
    rows = (
        db.query(BadgeAward, BadgeDefinition)
        .join(BadgeDefinition, BadgeAward.badge_definition_id == BadgeDefinition.id)
        .filter(BadgeAward.household_id == household.id)
        .order_by(BadgeAward.awarded_at.desc())
        .all()
    )
    return [
        BadgeAwardRead(
            key=defn.key,
            name=defn.name,
            description=defn.description,
            awarded_at=award.awarded_at,
            icon_url=defn.icon_url,
        )
        for award, defn in rows
    ]


# ---------- Stubs left for later ----------


@router.get("/dashboard")
def dashboard(db: Annotated[Session, Depends(get_db)]):
    return {
        "saved_this_month_usd": 0,
        "waste_avoided_usd": 0,
        "todo": "Aggregate SavingsEvent + FoodWasteEvent + Streak rows",
    }


@router.get("/savings")
def list_savings(db: Annotated[Session, Depends(get_db)]):
    return {"events": [], "todo": "List SavingsEvent for household"}


@router.post("/savings")
def log_savings(db: Annotated[Session, Depends(get_db)]):
    return {"event": None, "todo": "Persist SavingsEvent"}


@router.get("/budgets")
def list_budgets(db: Annotated[Session, Depends(get_db)]):
    return {"budgets": [], "todo": "List Budget rows for current month"}


@router.post("/budgets")
def set_budget(db: Annotated[Session, Depends(get_db)]):
    return {"budget": None, "todo": "Upsert Budget(household, category, month_start)"}
