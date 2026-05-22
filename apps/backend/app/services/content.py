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
