"""Tests for the recipe-suggestion content schemas."""

from __future__ import annotations

from app.schemas.content import RecipeSuggestion, VideoIngredients


def test_video_ingredients_parses_llm_shape():
    parsed = VideoIngredients.model_validate(
        {"is_recipe_video": True, "dish_name": "Tomato Pasta", "ingredients": ["tomato", "pasta"]}
    )
    assert parsed.is_recipe_video is True
    assert parsed.ingredients == ["tomato", "pasta"]


def test_video_ingredients_defaults():
    parsed = VideoIngredients.model_validate({"is_recipe_video": False})
    assert parsed.dish_name is None
    assert parsed.ingredients == []


def test_recipe_suggestion_round_trips():
    import uuid

    s = RecipeSuggestion(
        id=uuid.uuid4(),
        provider="youtube",
        external_id="abc",
        title="t",
        url=None,
        author=None,
        thumbnail_url=None,
        duration_seconds=None,
        match_score=3.0,
        matched_ingredients=["tomato"],
        match_reason="Uses tomato",
    )
    assert s.match_score == 3.0
