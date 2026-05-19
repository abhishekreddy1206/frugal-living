"""Daily briefing generation + persistence."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.ai import Briefing
from app.models.core import Household
from app.services.events import emit_event
from app.services.llm import generate_briefing as llm_generate_briefing
from app.services.pantry import snapshot_pantry
from app.services.waste import savings_rollup


def _start_of_today_utc() -> datetime:
    now = datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def get_today(db: Session, household: Household) -> Briefing | None:
    return (
        db.query(Briefing)
        .filter(
            Briefing.household_id == household.id,
            Briefing.for_date == _start_of_today_utc(),
            Briefing.deleted_at.is_(None),
        )
        .one_or_none()
    )


def get_or_generate_today(
    db: Session,
    *,
    household: Household,
    user_id,
    force: bool = False,
) -> Briefing:
    """Return today's briefing, generating it if missing.

    When force=True with an existing briefing, the row is UPDATED in place — the
    DB has a unique (household_id, for_date) index without a deleted_at predicate,
    so we can't soft-delete-and-insert.
    """
    existing = get_today(db, household)
    if existing is not None and not force:
        return existing

    pantry = snapshot_pantry(db, household)
    savings = savings_rollup(db, household=household, period_days=7)
    ai = llm_generate_briefing(pantry, savings)
    metadata = {
        "pantry_size": len(pantry),
        "expiring_soon_count": sum(
            1
            for p in pantry
            if p.expires_in_days is not None and p.expires_in_days <= 5
        ),
        "savings_net_usd": savings.net_savings_usd,
    }

    if existing is not None and force:
        existing.headline = ai.headline
        existing.body_markdown = ai.body_markdown
        existing.was_read = False
        existing.metadata_ = metadata
        existing.updated_at = datetime.now(UTC)
        briefing = existing
        db.flush()
    else:
        briefing = Briefing(
            household_id=household.id,
            for_date=_start_of_today_utc(),
            headline=ai.headline,
            body_markdown=ai.body_markdown,
            delivered_via=["in_app"],
            was_read=False,
            metadata_=metadata,
        )
        db.add(briefing)
        db.flush()

    emit_event(
        db,
        event_type="ai.briefing.generated",
        household_id=household.id,
        user_id=user_id,
        entity_type="briefing",
        entity_id=briefing.id,
        payload={
            "headline": briefing.headline,
            "for_date": briefing.for_date.isoformat(),
            "regenerated": existing is not None and force,
        },
    )
    return briefing


def mark_read(db: Session, briefing: Briefing) -> Briefing:
    briefing.was_read = True
    db.flush()
    return briefing
