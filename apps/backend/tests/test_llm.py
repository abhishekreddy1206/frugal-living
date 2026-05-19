"""Tests for app.services.llm."""
from __future__ import annotations

import base64
import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.schemas.food import (
    AIWeekPlan,
    ExtractedPantry,
    PantrySnapshotItem,
    StretchConstraints,
    StretchSuggestions,
    WeekPlanConstraints,
)
from app.services import llm

# ---------- _extract_json ----------

def test_extract_json_bare():
    assert llm._extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    assert llm._extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_with_preamble():
    text = 'Here is your data:\n\n{"items": [{"raw_name": "rice"}]}\n\nHope that helps!'
    assert llm._extract_json(text) == {"items": [{"raw_name": "rice"}]}


def test_extract_json_raises_when_no_json():
    with pytest.raises(ValueError, match="could not extract JSON"):
        llm._extract_json("just text, no json at all")


# ---------- extract_pantry_from_image (mocked) ----------

def _mock_response(payload: dict) -> SimpleNamespace:
    text_block = SimpleNamespace(type="text", text=json.dumps(payload))
    return SimpleNamespace(content=[text_block])


@pytest.fixture
def mock_client(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(llm, "get_client", lambda: client)
    return client


def test_extract_pantry_from_image_happy_path(mock_client):
    mock_client.messages.create.return_value = _mock_response(
        {
            "items": [
                {
                    "raw_name": "Roma tomatoes",
                    "quantity": 6,
                    "unit": "each",
                    "confidence": 0.92,
                    "suggested_expires_at": None,
                    "notes": None,
                },
                {
                    "raw_name": "olive oil",
                    "quantity": 1,
                    "unit": "bottle",
                    "confidence": 0.98,
                    "suggested_expires_at": None,
                    "notes": "looks half full",
                },
            ]
        }
    )

    result = llm.extract_pantry_from_image("BASE64DATA" * 10)

    assert isinstance(result, ExtractedPantry)
    assert len(result.items) == 2
    assert result.items[0].raw_name == "Roma tomatoes"
    assert result.items[0].quantity == 6
    assert result.items[1].notes == "looks half full"

    # Verify request shape
    kwargs = mock_client.messages.create.call_args.kwargs
    assert kwargs["model"] == llm.MODEL_VISION
    assert "image" in str(kwargs["messages"])
    assert kwargs["messages"][0]["content"][0]["type"] == "image"
    assert kwargs["messages"][0]["content"][0]["source"]["media_type"] == "image/jpeg"


def test_extract_pantry_from_image_strips_fences(mock_client):
    text_block = SimpleNamespace(
        type="text",
        text='```json\n{"items": [{"raw_name": "rice", "confidence": 0.9}]}\n```',
    )
    mock_client.messages.create.return_value = SimpleNamespace(content=[text_block])

    result = llm.extract_pantry_from_image("BASE64DATA" * 10)
    assert len(result.items) == 1
    assert result.items[0].raw_name == "rice"


def test_extract_pantry_from_image_passes_media_type(mock_client):
    mock_client.messages.create.return_value = _mock_response({"items": []})
    llm.extract_pantry_from_image("BASE64DATA" * 10, media_type="image/png")
    kwargs = mock_client.messages.create.call_args.kwargs
    assert kwargs["messages"][0]["content"][0]["source"]["media_type"] == "image/png"


def test_extract_pantry_from_image_raises_on_empty_response(mock_client):
    mock_client.messages.create.return_value = SimpleNamespace(content=[])
    with pytest.raises(ValueError, match="no text content"):
        llm.extract_pantry_from_image("BASE64DATA" * 10)


# ---------- stretch_recipes_for_pantry (mocked) ----------


def _stretch_response(recipes: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps({"recipes": recipes}))]
    )


def test_stretch_happy_path(mock_client):
    mock_client.messages.create.return_value = _stretch_response(
        [
            {
                "name": "Tomato Garlic Pasta",
                "description": "Simple weeknight pasta.",
                "servings": 4,
                "prep_time_min": 10,
                "cook_time_min": 15,
                "cuisine": "Italian",
                "difficulty": "easy",
                "tags": ["quick", "vegetarian"],
                "estimated_cost_usd": 2.50,
                "estimated_cost_per_serving_usd": 0.62,
                "ingredients": [
                    {
                        "raw_name": "spaghetti",
                        "quantity": 1,
                        "unit": "lb",
                        "is_optional": False,
                        "substitutions": ["any long pasta"],
                    },
                    {
                        "raw_name": "garlic",
                        "quantity": 4,
                        "unit": "clove",
                        "is_optional": False,
                        "substitutions": [],
                    },
                ],
                "steps": [
                    {"content": "Boil pasta.", "duration_seconds": 600},
                    {"content": "Sauté garlic.", "duration_seconds": 120},
                ],
                "pantry_items_used": ["spaghetti", "garlic"],
            }
        ]
    )

    pantry = [
        PantrySnapshotItem(
            raw_name="spaghetti", quantity=1, unit="lb",
            expires_in_days=720, ingredient_id=None,
        ),
        PantrySnapshotItem(
            raw_name="garlic", quantity=1, unit="head",
            expires_in_days=21, ingredient_id=None,
        ),
    ]
    result = llm.stretch_recipes_for_pantry(pantry, StretchConstraints())

    assert isinstance(result, StretchSuggestions)
    assert len(result.recipes) == 1
    r = result.recipes[0]
    assert r.name == "Tomato Garlic Pasta"
    assert r.difficulty == "easy"
    assert len(r.ingredients) == 2
    assert r.ingredients[0].substitutions == ["any long pasta"]
    assert "spaghetti" in r.pantry_items_used

    kwargs = mock_client.messages.create.call_args.kwargs
    assert kwargs["model"] == llm.MODEL_FAST
    # Pantry summary appears in the user message
    user_msg = kwargs["messages"][0]["content"]
    assert "spaghetti" in user_msg
    assert "garlic" in user_msg


def test_stretch_passes_constraints_to_prompt(mock_client):
    mock_client.messages.create.return_value = _stretch_response([])
    llm.stretch_recipes_for_pantry(
        [],
        StretchConstraints(
            max_prep_min=15,
            max_cook_min=30,
            count=3,
            cuisines=["Thai", "Mexican"],
            meal_type="dinner",
        ),
    )
    user_msg = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Return 3 recipes" in user_msg
    assert "<= 15" in user_msg
    assert "<= 30" in user_msg
    assert "Thai" in user_msg
    assert "dinner" in user_msg


def test_stretch_empty_pantry_still_works(mock_client):
    mock_client.messages.create.return_value = _stretch_response([])
    result = llm.stretch_recipes_for_pantry([], StretchConstraints())
    assert result.recipes == []
    user_msg = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "pantry is empty" in user_msg


def test_stretch_rejects_malformed_difficulty(mock_client):
    """Pydantic validation should reject an out-of-domain difficulty value."""
    import pydantic
    mock_client.messages.create.return_value = _stretch_response(
        [
            {
                "name": "X",
                "servings": 2,
                "difficulty": "trivial",  # invalid
                "ingredients": [],
                "steps": [],
            }
        ]
    )
    with pytest.raises(pydantic.ValidationError):
        llm.stretch_recipes_for_pantry([], StretchConstraints())


# ---------- generate_weekly_plan (mocked) ----------


def _week_plan_response(plan: dict) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps(plan))]
    )


def _ai_recipe_dict(name: str) -> dict:
    return {
        "name": name,
        "description": f"{name} description",
        "servings": 4,
        "prep_time_min": 10,
        "cook_time_min": 20,
        "cuisine": "Italian",
        "difficulty": "easy",
        "tags": ["weeknight"],
        "estimated_cost_usd": 3.0,
        "estimated_cost_per_serving_usd": 0.75,
        "ingredients": [
            {"raw_name": "pasta", "quantity": 1, "unit": "lb",
             "is_optional": False, "substitutions": []},
        ],
        "steps": [{"content": "Cook.", "duration_seconds": 900}],
        "pantry_items_used": ["pasta"],
    }


def test_generate_weekly_plan_uses_opus_model(mock_client):
    from datetime import date as _date
    plan_payload = {
        "meals": [
            {
                "planned_date": str(_date.today()),
                "meal_type": "dinner",
                "recipe": _ai_recipe_dict("Pasta Night"),
                "rationale": "Uses your pasta from the pantry.",
            }
        ],
        "total_estimated_cost_usd": 5.0,
        "pantry_coverage_summary": "Uses 1 of 1 pantry items.",
    }
    mock_client.messages.create.return_value = _week_plan_response(plan_payload)

    result = llm.generate_weekly_plan(
        [],
        WeekPlanConstraints(
            week_start=_date.today(),
            target_budget_usd=30.0,
            dinners_per_week=1,
            dietary_constraints=["vegetarian"],
        ),
    )

    assert isinstance(result, AIWeekPlan)
    assert len(result.meals) == 1
    assert result.meals[0].recipe.name == "Pasta Night"
    assert result.meals[0].rationale.startswith("Uses your pasta")

    kwargs = mock_client.messages.create.call_args.kwargs
    assert kwargs["model"] == llm.MODEL_SMART  # Opus, not Sonnet
    user_msg = kwargs["messages"][0]["content"]
    assert "Target weekly budget" in user_msg
    assert "vegetarian" in user_msg


def test_generate_weekly_plan_includes_each_date(mock_client):
    from datetime import date as _date
    from datetime import timedelta as _td
    monday = _date(2026, 6, 1)
    mock_client.messages.create.return_value = _week_plan_response({"meals": []})

    llm.generate_weekly_plan(
        [], WeekPlanConstraints(week_start=monday, dinners_per_week=3)
    )

    user_msg = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    for i in range(3):
        assert (monday + _td(days=i)).isoformat() in user_msg
    # 4th day shouldn't appear
    assert (monday + _td(days=3)).isoformat() not in user_msg


# ---------- Live test (opt-in) ----------

@pytest.mark.skipif(
    os.getenv("LIVE_LLM") != "1",
    reason="Live LLM test only runs with LIVE_LLM=1",
)
def test_extract_pantry_from_image_live():
    """Hits the real Anthropic API. Burns tokens. Skip in CI by default."""
    # 1x1 transparent PNG
    tiny_png = base64.b64encode(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000d49444154789c63000100000005000100"
            "5d0d0a2d0000000049454e44ae426082"
        )
    ).decode()
    result = llm.extract_pantry_from_image(tiny_png, media_type="image/png")
    assert isinstance(result, ExtractedPantry)
