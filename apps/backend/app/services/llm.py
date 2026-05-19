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
from app.schemas.food import ExtractedPantry

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


def stretch_recipes_for_pantry(pantry_items: list[dict], constraints: dict) -> list[dict]:
    """Generate recipes optimized for what's on hand + budget + preferences. Sprint 2."""
    raise NotImplementedError("Implement in Sprint 2")


def generate_weekly_plan(household: dict, pantry: list[dict], constraints: dict) -> dict:
    """Generate 5-7 meals planned around pantry + budget. Sprint 3."""
    raise NotImplementedError("Implement in Sprint 3")


def generate_briefing(household: dict, pantry: list[dict], savings: list[dict]) -> dict:
    """Daily proactive briefing — what's expiring, what to cook, dollars saved."""
    raise NotImplementedError("Implement when daily-briefing job lands")


def rank_content_for_household(items: list[dict], household: dict) -> list[dict]:
    """Score curated content for relevance to this household's pantry + preferences."""
    raise NotImplementedError("Implement after first ingestion run")
