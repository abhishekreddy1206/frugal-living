"""Tracking module — savings dashboard, streaks, badges."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter()


# ---------- Dashboard ----------

@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    """Headline numbers: dollars saved this month, waste avoided, streaks active."""
    return {
        "saved_this_month_usd": 0,
        "waste_avoided_usd": 0,
        "active_streaks": [],
        "recent_savings": [],
        "todo": "Aggregate SavingsEvent + FoodWasteEvent + Streak rows",
    }


# ---------- Savings events ----------

@router.get("/savings")
def list_savings(db: Session = Depends(get_db)):
    return {"events": [], "todo": "List SavingsEvent for household"}


@router.post("/savings")
def log_savings(db: Session = Depends(get_db)):
    """Manually log a savings event (most are emitted by other services automatically)."""
    return {"event": None, "todo": "Persist SavingsEvent"}


# ---------- Budgets ----------

@router.get("/budgets")
def list_budgets(db: Session = Depends(get_db)):
    return {"budgets": [], "todo": "List Budget rows for current month"}


@router.post("/budgets")
def set_budget(db: Session = Depends(get_db)):
    return {"budget": None, "todo": "Upsert Budget(household, category, month_start)"}


# ---------- Streaks + badges ----------

@router.get("/streaks")
def list_streaks(db: Session = Depends(get_db)):
    return {"streaks": [], "todo": "List Streak rows for household"}


@router.get("/badges")
def list_badges(db: Session = Depends(get_db)):
    return {"badges": [], "todo": "Join BadgeAward + BadgeDefinition"}
