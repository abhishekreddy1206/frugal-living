"""
Content enrichment + pantry-fit ranking.

Enrichment runs once per video: fetch the YouTube description (if not already
stored), ask Claude for the ingredient list, resolve those to canonical
food.ingredients IDs, and store everything on the ContentItem. Ranking is
rule-based set overlap against the live pantry — no LLM call, per request.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.models.content import ContentItem
from app.models.core import Household
from app.models.food import Ingredient, PantryItem
from app.services import llm
from app.services.events import emit_event
from app.services.ingredients import resolve_ingredient
from app.services.youtube import fetch_video_details

logger = logging.getLogger(__name__)

_ENRICHMENT_VERSION = 1
_EXPIRING_SOON_DAYS = 3
_EXPIRING_WEIGHT = 2.0  # a pantry ingredient expiring soon scores this; others 1.0


def enrich_content_item(db: Session, item: ContentItem) -> bool:
    """Enrich one ContentItem with extracted ingredients. Best-effort + idempotent.

    Returns True on success. On any failure, logs and returns False — the item is
    left un-enriched (no `metadata_["enrichment"]`) so the backfill can retry it.
    No DB flush happens on the failure path, so the session is never poisoned.
    """
    try:
        # Step 1: ensure the description text is present (old items lack it).
        if not item.body:
            details = fetch_video_details(item.external_id)
            if details is not None:
                item.body = details.description
                item.duration_seconds = details.duration_seconds
                if details.published_at is not None:
                    item.published_at = details.published_at
                item.metadata_ = {**item.metadata_, "youtube_tags": details.youtube_tags}

        youtube_tags = list(item.metadata_.get("youtube_tags") or [])

        # Step 2: extract ingredients via Claude.
        extracted = llm.extract_video_ingredients(item.title, item.body or "", youtube_tags)

        # Step 3: resolve to canonical ingredient IDs (keep all names as display tags).
        ingredient_ids: list[str] = []
        for name in extracted.ingredients:
            resolved = resolve_ingredient(db, name)
            if resolved is not None:
                ingredient_ids.append(str(resolved))

        item.tags = list(extracted.ingredients)
        if extracted.dish_name:
            item.summary = extracted.dish_name
        item.metadata_ = {
            **item.metadata_,
            "ingredient_ids": ingredient_ids,
            "is_recipe_video": extracted.is_recipe_video,
            "enrichment": {
                "version": _ENRICHMENT_VERSION,
                "enriched_at": datetime.now(UTC).isoformat(),
            },
        }
        db.flush()
        emit_event(
            db,
            event_type="content.item.enriched",
            entity_type="content_item",
            entity_id=item.id,
            payload={
                "is_recipe_video": extracted.is_recipe_video,
                "ingredient_count": len(ingredient_ids),
            },
        )
        return True
    except Exception:  # noqa: BLE001 — enrichment is best-effort, never fatal
        logger.exception("enrichment failed for content item %s", item.id)
        return False


@dataclass
class RankedVideo:
    item: ContentItem
    match_score: float
    matched_ingredients: list[str]  # canonical display names
    match_reason: str


@dataclass
class EnrichResult:
    enriched: int
    failed: int
    remaining: int


def _join_names(names: list[str]) -> str:
    """'a' / 'a and b' / 'a, b, and c'."""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{', '.join(names[:-1])}, and {names[-1]}"


def _match_reason(matched_names: list[str], soonest: tuple[str, int] | None) -> str:
    base = f"Uses {_join_names(matched_names)}"
    if soonest is None:
        return base
    name, days = soonest
    when = "today" if days <= 0 else f"in {days} day{'s' if days != 1 else ''}"
    return f"{base} — {name} expires {when}"


def rank_videos_for_pantry(
    db: Session, *, household: Household, limit: int = 12
) -> tuple[list[RankedVideo], int]:
    """Rank enriched cooking videos by ingredient overlap with the household's pantry.

    Returns (videos sorted best-first, pantry_size). Zero-overlap videos are dropped.
    """
    # Pantry: ingredient_id -> soonest expiry in days (None = no expiry).
    today = date.today()
    pantry: dict[uuid.UUID, int | None] = {}
    pantry_rows = (
        db.query(PantryItem)
        .filter(
            PantryItem.household_id == household.id,
            PantryItem.deleted_at.is_(None),
            PantryItem.ingredient_id.isnot(None),
        )
        .all()
    )
    for row in pantry_rows:
        if row.ingredient_id is None:
            continue
        days = (row.expires_at - today).days if row.expires_at else None
        if row.ingredient_id not in pantry:
            pantry[row.ingredient_id] = days
        else:
            prev = pantry[row.ingredient_id]
            if days is not None and (prev is None or days < prev):
                pantry[row.ingredient_id] = days

    if not pantry:
        return [], 0

    names_by_id = {r.id: r.display_name for r in db.query(Ingredient).all()}

    items = db.query(ContentItem).filter(ContentItem.deleted_at.is_(None)).all()
    ranked: list[RankedVideo] = []
    for item in items:
        meta = item.metadata_ or {}
        if not meta.get("is_recipe_video"):
            continue
        try:
            video_ids = {uuid.UUID(x) for x in meta.get("ingredient_ids") or []}
        except (ValueError, TypeError):
            continue
        matched = video_ids & set(pantry.keys())
        if not matched:
            continue

        score = 0.0
        expiring: list[tuple[str, int]] = []
        matched_names: list[str] = []
        for ing_id in matched:
            name = names_by_id.get(ing_id, "an ingredient")
            matched_names.append(name)
            days = pantry[ing_id]
            if days is not None and days <= _EXPIRING_SOON_DAYS:
                score += _EXPIRING_WEIGHT
                expiring.append((name, days))
            else:
                score += 1.0

        matched_names.sort()
        soonest = min(expiring, key=lambda x: x[1]) if expiring else None
        ranked.append(
            RankedVideo(
                item=item,
                match_score=score,
                matched_ingredients=matched_names,
                match_reason=_match_reason(matched_names, soonest),
            )
        )

    ranked.sort(key=lambda r: r.match_score, reverse=True)
    return ranked[:limit], len(pantry)


def enrich_pending(db: Session, *, limit: int = 20) -> EnrichResult:
    """Backfill: enrich up to `limit` ContentItems with no enrichment metadata.

    Flushes via `enrich_content_item`; the caller is responsible for the commit.
    """
    candidates = db.query(ContentItem).filter(ContentItem.deleted_at.is_(None)).all()
    todo = [it for it in candidates if not (it.metadata_ or {}).get("enrichment")]
    batch = todo[:limit]
    enriched = 0
    failed = 0
    for item in batch:
        if enrich_content_item(db, item):
            enriched += 1
        else:
            failed += 1
    return EnrichResult(enriched=enriched, failed=failed, remaining=max(0, len(todo) - len(batch)))
