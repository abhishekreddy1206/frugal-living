"""Centralized Claude client. Every tier uses this."""
from anthropic import Anthropic
from app.config import settings

client = Anthropic(api_key=settings.anthropic_api_key)

# Model selection by job:
MODEL_FAST = "claude-sonnet-4-6"      # routine recipe generation, planning, content ranking
MODEL_SMART = "claude-opus-4-7"        # hard reasoning, multi-constraint optimization
MODEL_VISION = "claude-sonnet-4-6"     # pantry photo extraction, receipt parsing
MODEL_HAIKU = "claude-haiku-4-5-20251001"  # cheap structured output, classification


# ---------- Vision ----------

def extract_pantry_from_image(image_base64: str, media_type: str = "image/jpeg") -> dict:
    """Photo -> list of pantry items with quantities + confidence. Stub."""
    raise NotImplementedError("Implement in Sprint 1")


def extract_receipt(image_base64: str, media_type: str = "image/jpeg") -> dict:
    """Receipt photo -> store, date, line items, total. Stub."""
    raise NotImplementedError("Implement alongside pantry capture")


# ---------- Recipes / planning ----------

def stretch_recipes_for_pantry(pantry_items: list[dict], constraints: dict) -> list[dict]:
    """Generate recipes optimized for what's on hand + budget + preferences. Stub."""
    raise NotImplementedError("Implement in Sprint 2")


def generate_weekly_plan(household: dict, pantry: list[dict], constraints: dict) -> dict:
    """Generate 5-7 meals planned around pantry + budget. Stub."""
    raise NotImplementedError("Implement in Sprint 3")


# ---------- Briefings ----------

def generate_briefing(household: dict, pantry: list[dict], savings: list[dict]) -> dict:
    """Generate the daily proactive briefing — what's expiring, what to cook, dollars saved."""
    raise NotImplementedError("Implement when daily-briefing job lands")


# ---------- Content ranking ----------

def rank_content_for_household(items: list[dict], household: dict) -> list[dict]:
    """Score curated content for relevance to this household's pantry + preferences."""
    raise NotImplementedError("Implement after first ingestion run")
