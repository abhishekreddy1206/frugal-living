"""
Preservation coach.

CLAUDE.md safety guardrails: botulism is a real risk with low-acid home canning.
This module:
  1. Provides a static catalog of methods + their safe categories (no LLM needed).
  2. Calls Claude for tailored advice but the prompt FORCEFULLY refuses unsafe
     guidance — low-acid water-bath canning is rejected before reaching the user.
  3. Persistence: PreservationJob rows track the lifecycle with a safety_check_passed
     gate. completed_at can only be set when safety_check_passed is true.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.core import Household, User
from app.models.food import PreservationJob
from app.schemas.food import (
    PreservationAdvice,
    PreservationAdviceRequest,
    PreservationJobCreate,
    PreservationMethodInfo,
)
from app.services.events import emit_event
from app.services.llm import preservation_advice as llm_preservation_advice

METHOD_CATALOG: list[PreservationMethodInfo] = [
    PreservationMethodInfo(
        method="canning_water_bath",
        label="Water-bath canning",
        safe_for=["high-acid"],
        typical_shelf_life_days=365,
        safety_notes=(
            "Safe ONLY for high-acid foods (pH ≤ 4.6): jams, jellies, pickles, "
            "fruit, and tomatoes WITH added acid. NEVER use water-bath canning "
            "for low-acid foods (vegetables, meats, beans) — botulism risk."
        ),
    ),
    PreservationMethodInfo(
        method="canning_pressure",
        label="Pressure canning",
        safe_for=["low-acid", "high-acid", "meat"],
        typical_shelf_life_days=365,
        safety_notes=(
            "Required for low-acid foods (vegetables, meats, beans, poultry, "
            "broth). Use a USDA-aligned tested pressure-canner recipe — do not "
            "improvise times or pressures."
        ),
    ),
    PreservationMethodInfo(
        method="freezing",
        label="Freezing",
        safe_for=["universal"],
        typical_shelf_life_days=180,
        safety_notes="Universally safe. Quality degrades faster than safety.",
    ),
    PreservationMethodInfo(
        method="dehydrating",
        label="Dehydrating",
        safe_for=["fruit", "vegetables", "meat"],
        typical_shelf_life_days=180,
        safety_notes=(
            "Use a dehydrator or oven held at the temperatures recommended by "
            "USDA Cooperative Extension. Jerky requires a precise temperature "
            "profile to avoid pathogen growth."
        ),
    ),
    PreservationMethodInfo(
        method="fermenting",
        label="Fermenting",
        safe_for=["vegetables", "dairy"],
        typical_shelf_life_days=90,
        safety_notes=(
            "Use proven salt brine ratios (typically 2–3% by weight) and keep "
            "the ferment submerged. Discard if mold or off-smells appear."
        ),
    ),
    PreservationMethodInfo(
        method="pickling",
        label="Pickling (vinegar)",
        safe_for=["vegetables"],
        typical_shelf_life_days=180,
        safety_notes=(
            "Use vinegar with at least 5% acidity. Refrigerator pickles only — "
            "shelf-stable pickling requires water-bath or pressure canning."
        ),
    ),
    PreservationMethodInfo(
        method="curing",
        label="Salt or sugar curing",
        safe_for=["meat", "fish"],
        typical_shelf_life_days=30,
        safety_notes=(
            "Curing meats requires precise nitrite/nitrate ratios. Follow a "
            "USDA-aligned cure formula; deviations risk botulism."
        ),
    ),
]


# Pre-defined low-acid categories that BLOCK water-bath canning before reaching the LLM.
_LOW_ACID_KEYWORDS = {
    "meat", "beef", "chicken", "pork", "fish", "salmon", "tuna",
    "bean", "lentil", "pea", "corn", "potato", "carrot", "squash",
    "pumpkin", "broth", "stock", "soup",
}


def is_low_acid(ingredient_name: str) -> bool:
    name = ingredient_name.lower()
    return any(kw in name for kw in _LOW_ACID_KEYWORDS)


def get_advice(request: PreservationAdviceRequest) -> PreservationAdvice:
    """Pre-LLM safety gate, then call Claude for tailored steps."""
    if request.method == "canning_water_bath" and is_low_acid(request.ingredient_name):
        return PreservationAdvice(
            is_safe=False,
            refusal_reason=(
                f"Water-bath canning is unsafe for {request.ingredient_name} — "
                "low-acid foods can grow Clostridium botulinum spores in canning "
                "jars. Use pressure canning (USDA-aligned recipe) instead."
            ),
            recommended_method="canning_pressure",
            safety_warnings=[
                "Botulism is a deadly toxin and tasteless. Do not improvise.",
            ],
            usda_references=[
                "https://nchfp.uga.edu/how/can_home.html",
                "USDA Complete Guide to Home Canning",
            ],
        )

    advice = llm_preservation_advice(request)
    # Belt-and-suspenders: even if the LLM's structure says is_safe=True,
    # never let water-bath + low-acid through.
    if (
        request.method == "canning_water_bath"
        and is_low_acid(request.ingredient_name)
    ):
        advice.is_safe = False
    return advice


def create_job(
    db: Session,
    *,
    household: Household,
    user: User | None,
    request: PreservationJobCreate,
) -> PreservationJob:
    job = PreservationJob(
        household_id=household.id,
        source_pantry_item_id=request.source_pantry_item_id,
        method=request.method,
        ingredient_name=request.ingredient_name,
        quantity_in=request.quantity_in,
        unit=request.unit,
        started_at=datetime.now(UTC),
        safety_check_passed=request.safety_check_passed,
        notes=request.notes,
    )
    db.add(job)
    db.flush()
    emit_event(
        db,
        event_type="food.preservation_job.started",
        household_id=household.id,
        user_id=user.id if user else None,
        entity_type="preservation_job",
        entity_id=job.id,
        payload={
            "method": job.method,
            "ingredient_name": job.ingredient_name,
            "safety_check_passed": job.safety_check_passed,
        },
    )
    return job


def complete_job(
    db: Session,
    *,
    household: Household,
    user: User | None,
    job: PreservationJob,
    quantity_out: float | None,
    expires_at,
    safety_notes: str | None,
) -> PreservationJob:
    if not job.safety_check_passed:
        raise ValueError(
            "Cannot mark preservation job complete until safety_check_passed=True"
        )
    job.completed_at = datetime.now(UTC)
    if quantity_out is not None:
        job.quantity_out = quantity_out
    if expires_at is not None:
        job.expires_at = expires_at
    elif job.expires_at is None:
        method_row = next(
            (m for m in METHOD_CATALOG if m.method == job.method), None
        )
        if method_row:
            today = datetime.now(UTC).date()
            job.expires_at = today + timedelta(days=method_row.typical_shelf_life_days)
    if safety_notes is not None:
        job.safety_notes = safety_notes

    emit_event(
        db,
        event_type="food.preservation_job.completed",
        household_id=household.id,
        user_id=user.id if user else None,
        entity_type="preservation_job",
        entity_id=job.id,
        payload={
            "method": job.method,
            "ingredient_name": job.ingredient_name,
            "quantity_out": float(job.quantity_out) if job.quantity_out is not None else None,
            "expires_at": job.expires_at.isoformat() if job.expires_at else None,
        },
    )
    return job
