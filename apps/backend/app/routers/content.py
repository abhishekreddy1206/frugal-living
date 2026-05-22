"""Content module — capture & feed external content (YouTube now; blog/Reddit later)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import CurrentHousehold, CurrentUser
from app.db import get_db
from app.models.content import ContentItem
from app.schemas.content import (
    CaptureRequest,
    ContentItemRead,
    EnrichResponse,
    FeedResponse,
    RecipeSuggestion,
    RecipeSuggestionsResponse,
)
from app.services.content import enrich_content_item, enrich_pending, rank_videos_for_pantry
from app.services.events import emit_event
from app.services.youtube import parse_video_id, resolve_video_metadata

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/feed", response_model=FeedResponse)
def feed(
    db: Annotated[Session, Depends(get_db)],
    topic: str | None = None,
    limit: int = Query(50, ge=1, le=200, description="Page size."),
    offset: int = Query(0, ge=0, description="Rows to skip for pagination."),
) -> FeedResponse:
    """Captured content, newest first. Optionally filtered by topic; paginated.

    `count` is the size of the returned page (not the global total) — the feed
    is a shared catalog (see the capture handler), so an unbounded total query
    isn't worth the second round-trip until a paging UI needs it.
    """
    query = db.query(ContentItem).filter(ContentItem.deleted_at.is_(None))
    if topic:
        query = query.filter(ContentItem.topic == topic)
    rows = query.order_by(ContentItem.created_at.desc()).limit(limit).offset(offset).all()
    return FeedResponse(
        items=[ContentItemRead.model_validate(r) for r in rows],
        count=len(rows),
    )


@router.get("/recipe-suggestions", response_model=RecipeSuggestionsResponse)
def recipe_suggestions(
    household: CurrentHousehold,
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(12, ge=1, le=50, description="Max suggestions to return."),
) -> RecipeSuggestionsResponse:
    """Saved cooking videos ranked by how well they fit the household's pantry."""
    ranked, pantry_size = rank_videos_for_pantry(db, household=household, limit=limit)
    return RecipeSuggestionsResponse(
        suggestions=[
            RecipeSuggestion(
                id=r.item.id,
                provider=r.item.provider,
                external_id=r.item.external_id,
                title=r.item.title,
                url=r.item.url,
                author=r.item.author,
                thumbnail_url=r.item.thumbnail_url,
                duration_seconds=r.item.duration_seconds,
                match_score=r.match_score,
                matched_ingredients=r.matched_ingredients,
                match_reason=r.match_reason,
            )
            for r in ranked
        ],
        pantry_size=pantry_size,
    )


@router.post("/enrich", response_model=EnrichResponse)
def enrich_pending_endpoint(
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(20, ge=1, le=100, description="Max items to enrich this call."),
) -> EnrichResponse:
    """Backfill enrichment for videos saved before this feature. Bounded by `limit`;
    re-call while `remaining > 0`."""
    result = enrich_pending(db, limit=limit)
    db.commit()
    return EnrichResponse(
        enriched=result.enriched, failed=result.failed, remaining=result.remaining
    )


@router.post("/capture", response_model=ContentItemRead)
def capture(
    request: CaptureRequest,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ContentItemRead:
    """Capture a YouTube video by URL into the shared content feed, then enrich it.

    Metadata resolves via the YouTube Data API (one call, rich) with an oEmbed
    fallback. Enrichment (ingredient extraction) is best-effort — a failure logs
    and leaves the item un-enriched; the capture still succeeds.
    """
    if parse_video_id(request.url) is None:
        raise HTTPException(422, "Only YouTube video URLs are supported right now")

    try:
        meta = resolve_video_metadata(request.url)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    existing = (
        db.query(ContentItem)
        .filter(
            ContentItem.provider == "youtube",
            ContentItem.external_id == meta.video_id,
        )
        .one_or_none()
    )
    if existing is not None:
        if existing.deleted_at is not None:
            existing.deleted_at = None  # re-capture an item that was removed
            db.commit()
            db.refresh(existing)
            logger.info("content item restored on re-capture: external_id=%s", meta.video_id)
        return ContentItemRead.model_validate(existing)

    item = ContentItem(
        provider="youtube",
        external_id=meta.video_id,
        title=meta.title,
        url=meta.url,
        author=meta.author,
        thumbnail_url=meta.thumbnail_url,
        topic=request.topic,
        body=meta.description,
        duration_seconds=meta.duration_seconds,
        published_at=meta.published_at,
        metadata_={"youtube_tags": meta.youtube_tags},
    )
    db.add(item)
    db.flush()

    emit_event(
        db,
        event_type="content.item.captured",
        household_id=household.id,
        user_id=user.id,
        entity_type="content_item",
        entity_id=item.id,
        payload={
            "provider": "youtube",
            "external_id": meta.video_id,
            "title": meta.title,
            "topic": request.topic,
        },
    )

    # Best-effort enrichment — `body` is already set, so this makes no extra
    # YouTube call; a failure inside is caught and never fails the capture.
    enrich_content_item(db, item)

    db.commit()
    db.refresh(item)
    logger.info("content item captured: external_id=%s topic=%s", meta.video_id, request.topic)
    return ContentItemRead.model_validate(item)


@router.delete("/items/{item_id}")
def delete_item(
    item_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Soft-delete a captured item (CLAUDE.md rule #4 — never hard delete)."""
    item = db.get(ContentItem, item_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(404, "content item not found")
    item.deleted_at = datetime.now(UTC)
    db.commit()
    logger.info("content item soft-deleted: id=%s", item_id)
    return {"status": "deleted", "id": str(item_id)}


# ---------- Stubs left for later (channel ingestion) ----------


@router.get("/sources")
def list_sources(db: Annotated[Session, Depends(get_db)]):
    return {"sources": [], "todo": "Wire to ContentSource (YouTube channels / RSS / subreddits)"}


@router.post("/ingest/run")
def run_ingestion_endpoint(db: Annotated[Session, Depends(get_db)]):
    """Manual trigger for channel polling. Production: run on a schedule."""
    return {"job_id": None, "todo": "Dispatch to services.youtube/reddit/blog_importer"}
