"""
Centralized Claude client. Per CLAUDE.md rule #7: every LLM call goes through here.

Model selection by job (see CLAUDE.md "LLM patterns"):
  MODEL_FAST   — Sonnet 4.6, recipe gen, planning, ranking
  MODEL_SMART  — Opus 4.7, multi-constraint optimization (meal plan)
  MODEL_VISION — Sonnet 4.6 (vision), pantry photo + receipt extraction
  MODEL_HAIKU  — Haiku 4.5, cheap classification

Prompts are versioned inline with a comment; move to prompts/<name>_v<N>.md when stable.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from anthropic import Anthropic

from app.config import settings
from app.schemas.food import (
    ExtractedPantry,
    PantrySnapshotItem,
    StretchConstraints,
    StretchSuggestions,
)

MODEL_FAST = "claude-sonnet-4-6"
MODEL_SMART = "claude-opus-4-7"
MODEL_VISION = "claude-sonnet-4-6"
MODEL_HAIKU = "claude-haiku-4-5-20251001"


@lru_cache(maxsize=1)
def get_client() -> Anthropic:
    """Lazy singleton so importing llm.py doesn't require a real API key."""
    return Anthropic(api_key=settings.anthropic_api_key)


# ---------- JSON extraction helper ----------

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _extract_json(text: str) -> dict | list:
    """Defensively pull JSON out of an LLM response (handles bare and fenced)."""
    stripped = _CODE_FENCE_RE.sub("", text).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        # Fallback: find first { or [ and try to parse to the matching brace
        for open_ch, close_ch in (("{", "}"), ("[", "]")):
            start = stripped.find(open_ch)
            end = stripped.rfind(close_ch)
            if 0 <= start < end:
                try:
                    return json.loads(stripped[start : end + 1])
                except json.JSONDecodeError:
                    continue
        raise ValueError(f"could not extract JSON from LLM response: {text[:200]!r}") from None


# ---------- Vision ----------

# v0.1 — initial pantry-extraction prompt
PANTRY_EXTRACT_SYSTEM = """You are a household inventory assistant. The user will send a photo of food items \
(pantry shelves, fridge interior, counter, grocery haul). Your job: identify every distinct \
food item visible and return a structured inventory.

Rules:
- Count each visible item. If you see "3 cans of tomatoes" return one entry with quantity=3, unit="can".
- Use the most specific name you can see ("San Marzano tomatoes" beats "tomatoes"). If the brand is \
visible, omit it from raw_name but you can mention it in notes.
- For loose produce or things without obvious count, set quantity=null.
- confidence is your subjective certainty 0..1 that the item exists in the photo at the quantity given.
- suggested_expires_at is YYYY-MM-DD; only set it when you can read a printed date OR the item is \
fresh produce with an obvious short shelf life (e.g. bananas ~7 days). Otherwise null.
- Do NOT include non-food items, packaging, or background objects.

Respond ONLY with valid JSON conforming to this schema; no preamble, no code fences:
{
  "items": [
    {
      "raw_name": "string",
      "quantity": number | null,
      "unit": "string | null",
      "confidence": number,
      "suggested_expires_at": "YYYY-MM-DD | null",
      "notes": "string | null"
    }
  ]
}"""


def extract_pantry_from_image(
    image_base64: str, media_type: str = "image/jpeg"
) -> ExtractedPantry:
    """Photo → structured pantry items. Sonnet 4.6 vision + Pydantic validation."""
    response = get_client().messages.create(
        model=MODEL_VISION,
        max_tokens=2048,
        system=PANTRY_EXTRACT_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_base64,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Extract every food item visible in this photo.",
                    },
                ],
            }
        ],
    )

    text_parts = [
        block.text for block in response.content if getattr(block, "type", None) == "text"
    ]
    if not text_parts:
        raise ValueError("LLM returned no text content")

    raw = _extract_json("".join(text_parts))
    return ExtractedPantry.model_validate(raw)


# ---------- Stubs awaiting later sprints ----------

def extract_receipt(image_base64: str, media_type: str = "image/jpeg") -> dict:
    """Receipt photo -> store, date, line items, total. Implement alongside Sprint 1.5."""
    raise NotImplementedError("Implement alongside pantry capture")


# v0.1 — initial recipe-stretcher prompt
RECIPE_STRETCH_SYSTEM = """You are a frugal home cook. The user shares their current pantry; \
you propose recipes that maximize use of what's already on hand and minimize what must be bought.

Rules:
- Prioritize ingredients that are expiring soon (lower expires_in_days = more urgency).
- Aim for cuisine variety across the suggested recipes.
- Prefer simple, low-equipment dishes a household cook can make on a weeknight.
- Each recipe must list every ingredient — both pantry items and anything that must be purchased.
- If a fresh-shopping ingredient is needed, suggest at least one substitution that comes from \
the pantry when plausible.
- pantry_items_used MUST list the exact raw_name strings from the pantry snapshot the recipe uses.
- difficulty must be "easy", "medium", or "hard".
- estimated_cost_per_serving_usd is your best US-grocery estimate for the cost of *new* ingredients \
that must be purchased, divided by servings.
- Skip macros/calorie info — we don't compete with MyFitnessPal.
- Do NOT advise low-acid water-bath canning or any unsafe preservation.

Respond ONLY with valid JSON conforming to this schema; no preamble, no code fences:
{
  "recipes": [
    {
      "name": "string",
      "description": "string | null",
      "servings": number,
      "prep_time_min": number | null,
      "cook_time_min": number | null,
      "cuisine": "string | null",
      "difficulty": "easy | medium | hard",
      "tags": ["string", ...],
      "estimated_cost_usd": number | null,
      "estimated_cost_per_serving_usd": number | null,
      "ingredients": [
        {
          "raw_name": "string",
          "quantity": number | null,
          "unit": "string | null",
          "is_optional": boolean,
          "substitutions": ["string", ...]
        }
      ],
      "steps": [
        { "content": "string", "duration_seconds": number | null }
      ],
      "pantry_items_used": ["pantry_raw_name", ...]
    }
  ]
}"""


def _format_pantry_for_prompt(pantry: list[PantrySnapshotItem]) -> str:
    """Compact text rendering of the pantry to send to Claude."""
    if not pantry:
        return "(pantry is empty)"
    lines = []
    for p in pantry:
        qty = f"{p.quantity} {p.unit}" if p.quantity is not None else "(unspecified)"
        exp = ""
        if p.expires_in_days is not None:
            if p.expires_in_days < 0:
                exp = " · EXPIRED"
            elif p.expires_in_days <= 3:
                exp = f" · expires in {p.expires_in_days}d"
            else:
                exp = f" · {p.expires_in_days}d shelf"
        lines.append(f"- {p.raw_name} ({qty}){exp}")
    return "\n".join(lines)


def _format_constraints(constraints: StretchConstraints) -> str:
    bits = [f"Return {constraints.count} recipes."]
    if constraints.max_prep_min is not None:
        bits.append(f"prep_time_min must be <= {constraints.max_prep_min}.")
    if constraints.max_cook_min is not None:
        bits.append(f"cook_time_min must be <= {constraints.max_cook_min}.")
    if constraints.prioritize_expiring:
        bits.append("Weight pantry items expiring within 5 days heavily.")
    if constraints.cuisines:
        bits.append(f"Prefer these cuisines if reasonable: {', '.join(constraints.cuisines)}.")
    if constraints.meal_type and constraints.meal_type != "any":
        bits.append(f"All recipes should be suitable for {constraints.meal_type}.")
    return " ".join(bits)


def stretch_recipes_for_pantry(
    pantry: list[PantrySnapshotItem],
    constraints: StretchConstraints,
) -> StretchSuggestions:
    """Given a pantry snapshot, ask Claude for N recipes that maximize pantry usage."""
    user_message = (
        f"Pantry snapshot:\n{_format_pantry_for_prompt(pantry)}\n\n"
        f"{_format_constraints(constraints)}"
    )

    response = get_client().messages.create(
        model=MODEL_FAST,
        max_tokens=4096,
        system=RECIPE_STRETCH_SYSTEM,
        messages=[{"role": "user", "content": user_message}],
    )

    text_parts = [
        block.text for block in response.content if getattr(block, "type", None) == "text"
    ]
    if not text_parts:
        raise ValueError("LLM returned no text content")

    raw = _extract_json("".join(text_parts))
    return StretchSuggestions.model_validate(raw)


def generate_weekly_plan(household: dict, pantry: list[dict], constraints: dict) -> dict:
    """Generate 5-7 meals planned around pantry + budget. Sprint 3."""
    raise NotImplementedError("Implement in Sprint 3")


def generate_briefing(household: dict, pantry: list[dict], savings: list[dict]) -> dict:
    """Daily proactive briefing — what's expiring, what to cook, dollars saved."""
    raise NotImplementedError("Implement when daily-briefing job lands")


def rank_content_for_household(items: list[dict], household: dict) -> list[dict]:
    """Score curated content for relevance to this household's pantry + preferences."""
    raise NotImplementedError("Implement after first ingestion run")
