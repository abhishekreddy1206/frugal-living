"""
Streaks + badges.

Streaks are derived from core.events rather than written directly — that keeps
core.events as the single source of truth and lets us recompute on schema/rule
changes. We persist Streak rows so the dashboard query is a single fetch.

Three streak kinds in v1:
  - cooked_from_pantry: max consecutive days ending today with a food.meal.cooked
  - meal_planned_week: count of weeks (last 12) with a food.meal_plan.created
  - zero_waste_week: consecutive 7-day windows with NO food.pantry_item.wasted
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.core import Event, Household
from app.models.tracking import BadgeAward, BadgeDefinition, Streak
from app.services.events import emit_event

BADGE_CATALOG: list[dict] = [
    {
        "key": "first_meal_cooked",
        "name": "First Meal Cooked",
        "description": "Cooked your first recipe from a Hearth suggestion.",
        "criteria": {"event_count": {"event_type": "food.meal.cooked", "threshold": 1}},
    },
    {
        "key": "week_cooked",
        "name": "Week-Long Cook",
        "description": "Cooked from the pantry every day for a week.",
        "criteria": {"streak_kind": "cooked_from_pantry", "threshold": 7},
    },
    {
        "key": "zero_waste_week",
        "name": "Zero-Waste Week",
        "description": "Made it a full week with no logged food waste.",
        "criteria": {"streak_kind": "zero_waste_week", "threshold": 1},
    },
    {
        "key": "first_plan",
        "name": "First Plan",
        "description": "Generated your first weekly meal plan.",
        "criteria": {"event_count": {"event_type": "food.meal_plan.created", "threshold": 1}},
    },
    {
        "key": "stocked_pantry",
        "name": "Stocked Pantry",
        "description": "Captured at least 25 pantry items.",
        "criteria": {"event_count": {"event_type": "food.pantry_item.added", "threshold": 25}},
    },
]


def seed_badge_definitions(db: Session) -> int:
    """Idempotently insert badge definitions. Returns number inserted."""
    existing = {row[0] for row in db.query(BadgeDefinition.key).all()}
    inserted = 0
    for spec in BADGE_CATALOG:
        if spec["key"] in existing:
            continue
        db.add(
            BadgeDefinition(
                key=spec["key"],
                name=spec["name"],
                description=spec["description"],
                criteria=spec["criteria"],
                is_active=True,
            )
        )
        inserted += 1
    if inserted:
        db.commit()
    return inserted


# ---------- Streak computation ----------


def _event_dates(
    db: Session, household: Household, event_type: str, since: datetime
) -> set[date]:
    rows = (
        db.query(Event.created_at)
        .filter(
            Event.household_id == household.id,
            Event.event_type == event_type,
            Event.created_at >= since,
        )
        .all()
    )
    return {r[0].date() for r in rows}


def _cooked_streak(db: Session, household: Household) -> tuple[int, int, date | None]:
    """Current consecutive-day streak ending today, plus all-time longest."""
    now = datetime.now(UTC)
    # 366 days for "all time" within reason; switch to full-table query if longer.
    days = _event_dates(db, household, "food.meal.cooked", now - timedelta(days=366))
    if not days:
        return 0, 0, None

    today = now.date()
    # Current streak: walk backwards from today
    current = 0
    d = today
    while d in days:
        current += 1
        d -= timedelta(days=1)

    # All-time longest: scan sorted set
    longest = 0
    run = 0
    prev: date | None = None
    for d in sorted(days):
        if prev is not None and d == prev + timedelta(days=1):
            run += 1
        else:
            run = 1
        longest = max(longest, run)
        prev = d
    last_event = max(days)
    return current, longest, last_event


def _zero_waste_streak(db: Session, household: Household) -> tuple[int, int, date | None]:
    """Weeks (rolling 7-day windows) with no waste events, ending today."""
    now = datetime.now(UTC)
    waste_days = _event_dates(db, household, "food.pantry_item.wasted", now - timedelta(days=366))
    today = now.date()
    current = 0
    while True:
        window_start = today - timedelta(days=(current + 1) * 7 - 1)
        window_end = today - timedelta(days=current * 7)
        if any(window_start <= d <= window_end for d in waste_days):
            break
        current += 1
        if current >= 52:  # cap at a year
            break
    longest = max(current, 0)
    last_event = max(waste_days) if waste_days else None
    return current, longest, last_event


def _plan_streak(db: Session, household: Household) -> tuple[int, int, date | None]:
    """How many of the last 12 weeks had at least one plan generated."""
    now = datetime.now(UTC)
    plan_days = _event_dates(db, household, "food.meal_plan.created", now - timedelta(days=84))
    if not plan_days:
        return 0, 0, None
    today = now.date()
    weeks_covered = 0
    for i in range(12):
        window_start = today - timedelta(days=(i + 1) * 7 - 1)
        window_end = today - timedelta(days=i * 7)
        if any(window_start <= d <= window_end for d in plan_days):
            weeks_covered += 1
        else:
            break
    return weeks_covered, weeks_covered, max(plan_days)


STREAK_KINDS = {
    "cooked_from_pantry": _cooked_streak,
    "zero_waste_week": _zero_waste_streak,
    "meal_planned_week": _plan_streak,
}


def recompute_streaks(db: Session, household: Household) -> list[Streak]:
    """Compute all streak kinds from events, upsert into tracking.streaks."""
    out: list[Streak] = []
    for kind, fn in STREAK_KINDS.items():
        current, longest, last_event = fn(db, household)
        row = (
            db.query(Streak)
            .filter(Streak.household_id == household.id, Streak.kind == kind)
            .one_or_none()
        )
        if row is None:
            row = Streak(
                household_id=household.id,
                kind=kind,
                current_length=current,
                longest_length=longest,
                last_event_on=last_event,
            )
            db.add(row)
        else:
            row.current_length = current
            row.longest_length = max(row.longest_length, longest)
            row.last_event_on = last_event
        out.append(row)
    db.flush()
    return out


# ---------- Badge evaluation ----------


def _count_event(db: Session, household: Household, event_type: str) -> int:
    return (
        db.query(Event)
        .filter(Event.household_id == household.id, Event.event_type == event_type)
        .count()
    )


def evaluate_badges(
    db: Session, household: Household, user_id: uuid.UUID | None
) -> list[BadgeAward]:
    """Check every BadgeDefinition; award any not yet held that meet criteria."""
    definitions = (
        db.query(BadgeDefinition).filter(BadgeDefinition.is_active.is_(True)).all()
    )
    held_def_ids = {
        row[0]
        for row in db.query(BadgeAward.badge_definition_id)
        .filter(BadgeAward.household_id == household.id)
        .all()
    }
    streaks = {s.kind: s for s in recompute_streaks(db, household)}

    awarded: list[BadgeAward] = []
    for d in definitions:
        if d.id in held_def_ids:
            continue
        crit = d.criteria or {}
        ok = False
        if "event_count" in crit:
            spec = crit["event_count"]
            if _count_event(db, household, spec["event_type"]) >= spec["threshold"]:
                ok = True
        elif "streak_kind" in crit:
            s = streaks.get(crit["streak_kind"])
            if s and s.current_length >= crit["threshold"]:
                ok = True
        if ok:
            award = BadgeAward(
                household_id=household.id,
                badge_definition_id=d.id,
            )
            db.add(award)
            db.flush()
            emit_event(
                db,
                event_type="tracking.badge.awarded",
                household_id=household.id,
                user_id=user_id,
                entity_type="badge_award",
                entity_id=award.id,
                payload={"badge_key": d.key, "badge_name": d.name},
            )
            awarded.append(award)
    return awarded
