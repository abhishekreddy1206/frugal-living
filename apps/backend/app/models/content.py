"""
Content module — external content ingestion + AI-generated articles.

Cross-cutting across all tiers. Tier A surfaces frugal-living YouTube channels,
recipe blogs, and Reddit threads. Tier S will surface bill-negotiation guides;
Tier B will surface community swap posts. Same schema, different `topic`.

All tables live in the `content` schema.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.core import TimestampMixin


class ContentSource(Base, TimestampMixin):
    """A channel/blog/subreddit we ingest content from."""
    __tablename__ = "sources"
    __table_args__ = (
        Index("idx_sources_provider_kind", "provider", "kind"),
        {"schema": "content"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    # youtube | rss | reddit | manual
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    # channel | blog | subreddit | newsletter
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    # YouTube channel ID, RSS feed URL, subreddit name, etc.
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    topic: Mapped[str] = mapped_column(String(32), default="food", nullable=False)
    # food | bills | community | general — maps to tier
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class ContentItem(Base, TimestampMixin):
    """
    A single piece of curated or generated content — video, blog post, Reddit thread,
    or AI-generated article. Recipes can be `imported_from_content_id` to a row here.
    """
    __tablename__ = "items"
    __table_args__ = (
        Index("idx_items_source", "source_id"),
        Index("idx_items_topic_published", "topic", "published_at"),
        Index("idx_items_provider_external", "provider", "external_id", unique=True),
        {"schema": "content"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content.sources.id"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    # youtube | rss | reddit | ai_generated
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    # video ID, post slug, reddit thread id, or generated uuid for AI items

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # For YouTube: transcript. For blogs: extracted article body. For Reddit: thread + top comments.
    thumbnail_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    topic: Mapped[str] = mapped_column(String(32), default="food", nullable=False)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    # Optional links to derived recipes (one item can mention several recipes)
    derived_recipe_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), default=list, nullable=False
    )
    relevance_score: Mapped[float | None] = mapped_column(nullable=True)
    # set by ranking job — frugality / dietary fit / freshness
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class IngestionJob(Base, TimestampMixin):
    """One run of a content ingestion job (YouTube poll, RSS poll, Reddit poll, AI generation)."""
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        Index("idx_ingestion_jobs_status_started", "status", "started_at"),
        {"schema": "content"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content.sources.id"), nullable=True
    )
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # youtube_poll | rss_poll | reddit_poll | ai_generation | rerank
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    # pending | running | succeeded | failed
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    items_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_inserted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class ContentBookmark(Base, TimestampMixin):
    """A user has saved an item. Per-household so the whole house can see it."""
    __tablename__ = "bookmarks"
    __table_args__ = (
        Index("idx_bookmarks_household", "household_id"),
        {"schema": "content"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content.items.id"), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
