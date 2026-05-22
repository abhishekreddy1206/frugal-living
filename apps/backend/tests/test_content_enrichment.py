"""Tests for content enrichment."""
from __future__ import annotations

from app.models.content import ContentItem
from app.models.core import Event
from app.schemas.content import VideoIngredients
from app.services import content, llm
from app.services.youtube import VideoDetails


def _make_item(db, *, body="A recipe with tomato and rice.", metadata=None):
    item = ContentItem(
        provider="youtube",
        external_id="vid123",
        title="One-Pot Tomato Rice",
        url="https://www.youtube.com/watch?v=vid123",
        body=body,
        metadata_=metadata or {},
    )
    db.add(item)
    db.flush()
    return item


def test_enrich_content_item_writes_ingredients_and_metadata(db, monkeypatch):
    monkeypatch.setattr(
        llm,
        "extract_video_ingredients",
        lambda title, description, tags: VideoIngredients(
            is_recipe_video=True, dish_name="Tomato Rice", ingredients=["tomato", "rice"]
        ),
    )
    item = _make_item(db)
    ok = content.enrich_content_item(db, item)
    assert ok is True
    assert item.metadata_["is_recipe_video"] is True
    assert item.summary == "Tomato Rice"
    assert set(item.tags) == {"tomato", "rice"}
    # "tomato" and "rice" are seeded starter ingredients → both resolve to IDs.
    assert len(item.metadata_["ingredient_ids"]) == 2
    assert "enrichment" in item.metadata_
    events = db.query(Event).filter(Event.event_type == "content.item.enriched").all()
    assert len(events) == 1


def test_enrich_content_item_fetches_details_when_body_missing(db, monkeypatch):
    monkeypatch.setattr(
        content,
        "fetch_video_details",
        lambda video_id: VideoDetails(
            title="t", author="a", description="Uses rice.", youtube_tags=["rice"],
            duration_seconds=120, published_at=None,
        ),
    )
    monkeypatch.setattr(
        llm,
        "extract_video_ingredients",
        lambda title, description, tags: VideoIngredients(
            is_recipe_video=True, dish_name=None, ingredients=["rice"]
        ),
    )
    item = _make_item(db, body=None)
    ok = content.enrich_content_item(db, item)
    assert ok is True
    assert item.body == "Uses rice."
    assert item.duration_seconds == 120


def test_enrich_content_item_is_best_effort_on_llm_failure(db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(llm, "extract_video_ingredients", boom)
    item = _make_item(db)
    ok = content.enrich_content_item(db, item)
    assert ok is False
    assert "enrichment" not in item.metadata_  # left un-enriched
