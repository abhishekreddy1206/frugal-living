"""Tests for pantry-fit ranking and the enrichment backfill."""
from __future__ import annotations

from datetime import date, timedelta

from app.auth import DEV_HOUSEHOLD_ID
from app.models.content import ContentItem
from app.models.core import Household
from app.models.food import Ingredient, PantryItem
from app.schemas.content import VideoIngredients
from app.services import content, llm


def _ingredient_id(db, canonical: str):
    return db.query(Ingredient.id).filter(Ingredient.canonical_name == canonical).scalar()


def _video(db, *, title, ingredient_ids, is_recipe=True):
    item = ContentItem(
        provider="youtube",
        external_id=f"v-{title}",
        title=title,
        metadata_={
            "ingredient_ids": [str(i) for i in ingredient_ids],
            "is_recipe_video": is_recipe,
            "enrichment": {"version": 1, "enriched_at": "2026-05-21T00:00:00+00:00"},
        },
    )
    db.add(item)
    db.flush()
    return item


def _pantry(db, ingredient_id, *, expires_in_days=None):
    household = db.get(Household, DEV_HOUSEHOLD_ID)
    expires = date.today() + timedelta(days=expires_in_days) if expires_in_days is not None else None
    db.add(
        PantryItem(
            household_id=household.id,
            ingredient_id=ingredient_id,
            raw_name="x",
            expires_at=expires,
        )
    )
    db.flush()


def test_rank_orders_by_overlap_and_excludes_zero_match(db):
    household = db.get(Household, DEV_HOUSEHOLD_ID)
    tomato = _ingredient_id(db, "tomato")
    rice = _ingredient_id(db, "rice")
    egg = _ingredient_id(db, "egg")
    _pantry(db, tomato)
    _pantry(db, rice)
    two_match = _video(db, title="Tomato Rice", ingredient_ids=[tomato, rice])
    one_match = _video(db, title="Tomato Toast", ingredient_ids=[tomato])
    _video(db, title="Egg Curry", ingredient_ids=[egg])  # zero overlap -> excluded

    ranked, pantry_size = content.rank_videos_for_pantry(db, household=household, limit=12)
    assert pantry_size == 2
    assert [r.item.id for r in ranked] == [two_match.id, one_match.id]


def test_rank_weights_expiring_ingredients(db):
    household = db.get(Household, DEV_HOUSEHOLD_ID)
    tomato = _ingredient_id(db, "tomato")
    _pantry(db, tomato, expires_in_days=1)  # expiring soon
    _video(db, title="Tomato Soup", ingredient_ids=[tomato])
    ranked, _ = content.rank_videos_for_pantry(db, household=household, limit=12)
    assert ranked[0].match_score >= 2.0  # expiring weight applied
    assert "expire" in ranked[0].match_reason.lower()


def test_rank_excludes_non_recipe_videos(db):
    household = db.get(Household, DEV_HOUSEHOLD_ID)
    tomato = _ingredient_id(db, "tomato")
    _pantry(db, tomato)
    _video(db, title="Not cooking", ingredient_ids=[tomato], is_recipe=False)
    ranked, _ = content.rank_videos_for_pantry(db, household=household, limit=12)
    assert ranked == []


def test_enrich_pending_processes_unenriched_only(db, monkeypatch):
    monkeypatch.setattr(
        llm,
        "extract_video_ingredients",
        lambda title, description, tags: VideoIngredients(
            is_recipe_video=True, dish_name=None, ingredients=["rice"]
        ),
    )
    # one already-enriched, one not
    _video(db, title="Enriched", ingredient_ids=[])
    raw = ContentItem(provider="youtube", external_id="raw1", title="Raw Rice Bowl", body="rice")
    db.add(raw)
    db.flush()

    result = content.enrich_pending(db, limit=10)
    assert result.enriched == 1
    assert result.remaining == 0
