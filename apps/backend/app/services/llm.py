"""
Centralized Claude client. Per CLAUDE.md rule #7: every LLM call goes through here.

Transport: calls route through the **Claude Code CLI** (`claude -p`), so no
ANTHROPIC_API_KEY is needed — the CLI authenticates with the local Claude Code
subscription. This is a temporary arrangement; to switch back to the Anthropic
API, restore the SDK client in `get_client()` (the reference body is in its
docstring). Nothing else in this module changes — `_ClaudeCliClient` is a
drop-in stand-in for `anthropic.Anthropic`.

Note: the CLI transport has no output-token cap — the `max_tokens` passed to
`create()` is accepted for SDK-signature compatibility but ignored. Response
length and cost discipline therefore rely entirely on prompt wording (see
CLAUDE.md "Cost discipline"); restoring the SDK transport restores the cap.

Model selection by job (see CLAUDE.md "LLM patterns"):
  MODEL_FAST   — Sonnet 4.6, recipe gen, planning, ranking
  MODEL_SMART  — Opus 4.7, multi-constraint optimization (meal plan)
  MODEL_VISION — Sonnet 4.6 (vision), pantry photo + receipt extraction
  MODEL_HAIKU  — Haiku 4.5, cheap classification

Prompts are versioned inline with a comment; move to prompts/<name>_v<N>.md when stable.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from types import SimpleNamespace

from app.schemas.ai import ChatTurnResult
from app.schemas.food import (
    AIBriefing,
    AIWeekPlan,
    ExtractedPantry,
    PantrySnapshotItem,
    PreservationAdvice,
    PreservationAdviceRequest,
    SavingsRollup,
    StretchConstraints,
    StretchSuggestions,
    WeekPlanConstraints,
)

logger = logging.getLogger(__name__)

MODEL_FAST = "claude-sonnet-4-6"
MODEL_SMART = "claude-opus-4-7"
MODEL_VISION = "claude-sonnet-4-6"
MODEL_HAIKU = "claude-haiku-4-5-20251001"

# Wall-clock budget for one `claude -p` invocation. Opus meal-plan calls are the
# slow path, so keep this generous.
_CLI_TIMEOUT_S = 600

_MEDIA_SUFFIX = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


@lru_cache(maxsize=1)
def _claude_bin() -> str:
    """Absolute path to the `claude` CLI, resolved once per process."""
    return shutil.which("claude") or "claude"


def _run_claude_cli(prompt: str, *, model: str, read_dir: str | None = None) -> str:
    """Invoke `claude -p`, feed the prompt on stdin, return the model's text.

    When `read_dir` is set, the Read tool is enabled and that directory is added
    to the CLI's allowed paths so a vision prompt can open an image file there.
    """
    args = [
        _claude_bin(),
        "-p",
        "--output-format",
        "json",
        "--no-session-persistence",
        "--model",
        model,
    ]
    if read_dir is not None:
        args += ["--allowedTools", "Read", "--add-dir", read_dir]

    # Strip ANTHROPIC_API_KEY so the CLI uses the Claude Code subscription
    # rather than trying to authenticate with a (possibly stale) API key.
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)

    logger.debug("claude CLI invoke: model=%s vision=%s", model, read_dir is not None)
    try:
        proc = subprocess.run(
            args,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=_CLI_TIMEOUT_S,
            env=env,
        )
    except FileNotFoundError as e:
        logger.error("claude CLI binary not found on PATH")
        raise RuntimeError(
            "claude CLI not found. Install Claude Code, or restore the Anthropic "
            "SDK client in app/services/llm.py:get_client()."
        ) from e
    except subprocess.TimeoutExpired as e:
        logger.error("claude CLI timed out after %ss (model=%s)", _CLI_TIMEOUT_S, model)
        raise RuntimeError(f"claude CLI timed out after {_CLI_TIMEOUT_S}s") from e

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:500]
        logger.error("claude CLI exited %s (model=%s): %s", proc.returncode, model, detail)
        raise RuntimeError(f"claude CLI exited {proc.returncode}: {detail}")

    stdout = proc.stdout.strip()
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        logger.warning("claude CLI stdout was not the expected JSON envelope; using raw text")
        return stdout  # tolerate a raw-text response
    if envelope.get("is_error"):
        logger.error("claude CLI returned an error envelope (model=%s)", model)
        raise RuntimeError(
            f"claude CLI returned an error: {str(envelope.get('result', stdout))[:500]}"
        )
    return envelope.get("result", stdout)


class _CliMessages:
    """SDK-compatible shim: mimics `anthropic.Anthropic().messages` over the CLI.

    Accepts the same `create(...)` call shape this module already uses and
    returns an object exposing `.content[i].type` / `.content[i].text`, so the
    public functions below are transport-agnostic.
    """

    def create(
        self,
        *,
        model: str,
        messages: list,
        system: str | None = None,
        max_tokens: int | None = None,  # noqa: ARG002 — CLI has no output cap
        **_ignored,
    ) -> SimpleNamespace:
        text_parts: list[str] = []
        image: tuple[str, str] | None = None  # (base64_data, media_type)
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, str):
                text_parts.append(content)
                continue
            for block in content or []:
                if block.get("type") == "text":
                    text_parts.append(block["text"])
                elif block.get("type") == "image":
                    src = block.get("source", {})
                    image = (src.get("data", ""), src.get("media_type", "image/jpeg"))

        sections: list[str] = []
        if system:
            sections.append(system)

        read_dir: str | None = None
        tmp_path: str | None = None
        if image is not None:
            data, media_type = image
            fd, tmp_path = tempfile.mkstemp(suffix=_MEDIA_SUFFIX.get(media_type, ".jpg"))
            with os.fdopen(fd, "wb") as f:
                f.write(base64.b64decode(data))
            read_dir = os.path.dirname(tmp_path)
            sections.append(
                f"An image is saved at {tmp_path}. Use the Read tool to open it, "
                f"then complete the task below using what you see in it."
            )

        sections.extend(text_parts)
        prompt = "\n\n".join(s for s in sections if s)

        try:
            result = _run_claude_cli(prompt, model=model, read_dir=read_dir)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

        return SimpleNamespace(content=[SimpleNamespace(type="text", text=result)])


class _ClaudeCliClient:
    """Drop-in stand-in for `anthropic.Anthropic`, backed by the Claude Code CLI."""

    def __init__(self) -> None:
        self.messages = _CliMessages()


@lru_cache(maxsize=1)
def get_client() -> _ClaudeCliClient:
    """The Claude transport every function in this module uses.

    Currently the Claude Code CLI — no API key required. To switch back to the
    Anthropic API, replace the body with:

        from anthropic import Anthropic
        from app.config import settings
        return Anthropic(api_key=settings.anthropic_api_key)
    """
    return _ClaudeCliClient()


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


def extract_pantry_from_image(image_base64: str, media_type: str = "image/jpeg") -> ExtractedPantry:
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


# v0.1 — initial weekly-plan prompt (Opus territory: multi-constraint optimization)
WEEK_PLAN_SYSTEM = """You are a household meal-plan optimizer. Generate a weekly dinner plan that:

1. MAXIMIZES use of the existing pantry, especially items expiring within 5 days.
2. STAYS UNDER the target weekly budget if one is given. Treat target_budget_usd as a hard ceiling \
on total_estimated_cost_usd — items the user already has do NOT count toward this; only new \
ingredients that must be purchased count.
3. RESPECTS dietary constraints (e.g. "vegetarian", "gluten-free", "no pork"). Never violate them.
4. VARIES cuisine across the week — at most one repeat cuisine in 7 days.
5. KEEPS difficulty appropriate for weeknight cooking — at most one "hard" recipe per week.
6. SPACES out high-effort meals — easy meals on weekdays, more involved on weekends if useful.

For each day in the requested range, output one full recipe (same shape as the stretcher), plus:
  - planned_date (YYYY-MM-DD)
  - meal_type: "dinner"
  - rationale: ONE sentence explaining why this slot picks this recipe, naming the pantry \
items it uses.

Also output:
  - total_estimated_cost_usd: sum of estimated_cost_usd across recipes (new-purchase cost only)
  - pantry_coverage_summary: one short sentence like "Uses 12 of 18 pantry items this week."

DO NOT include macros or calorie info. DO NOT suggest unsafe preservation methods.

Respond ONLY with valid JSON conforming to this schema; no preamble, no code fences:
{
  "meals": [
    {
      "planned_date": "YYYY-MM-DD",
      "meal_type": "dinner",
      "rationale": "string",
      "recipe": { /* full recipe object — name, description, servings, prep_time_min, cook_time_min, \
cuisine, difficulty, tags, estimated_cost_usd, estimated_cost_per_serving_usd, ingredients[], steps[], \
pantry_items_used[] */ }
    }
  ],
  "total_estimated_cost_usd": number | null,
  "pantry_coverage_summary": "string | null"
}"""


def _format_week_plan_constraints(pantry: list[PantrySnapshotItem], c: WeekPlanConstraints) -> str:
    from datetime import timedelta as _td

    dates = [c.week_start + _td(days=i) for i in range(c.dinners_per_week)]
    bits = [
        f"Generate dinner plans for: {', '.join(d.isoformat() for d in dates)}.",
    ]
    if c.target_budget_usd is not None:
        bits.append(f"Target weekly budget for new purchases: ${c.target_budget_usd:.2f}.")
    if c.max_cost_per_serving_usd is not None:
        bits.append(f"Cap estimated_cost_per_serving_usd at ${c.max_cost_per_serving_usd:.2f}.")
    if c.dietary_constraints:
        bits.append(f"Dietary constraints (must respect all): {', '.join(c.dietary_constraints)}.")
    if c.notes:
        bits.append(f"User notes: {c.notes}")
    return "\n".join(
        [
            "Pantry snapshot:",
            _format_pantry_for_prompt(pantry),
            "",
            *bits,
        ]
    )


def generate_weekly_plan(
    pantry: list[PantrySnapshotItem],
    constraints: WeekPlanConstraints,
) -> AIWeekPlan:
    """Generate a multi-constraint weekly dinner plan via Opus 4.7."""
    user_message = _format_week_plan_constraints(pantry, constraints)

    response = get_client().messages.create(
        model=MODEL_SMART,
        max_tokens=8192,
        system=WEEK_PLAN_SYSTEM,
        messages=[{"role": "user", "content": user_message}],
    )

    text_parts = [
        block.text for block in response.content if getattr(block, "type", None) == "text"
    ]
    if not text_parts:
        raise ValueError("LLM returned no text content")

    raw = _extract_json("".join(text_parts))
    return AIWeekPlan.model_validate(raw)


# v0.1 — daily briefing prompt
BRIEFING_SYSTEM = """You are Hearth — a warm, frugal home assistant writing a short daily \
briefing for one household.

Tone: human, encouraging, specific. No emojis except in section headers if useful. No marketing speak. \
Use the household's pantry + this week's savings as concrete anchors.

Always include:
  1. A short headline (≤ 80 chars) that captures today's most useful nudge.
  2. A body in Markdown with 2–4 short sections, e.g.:
     - **Expiring soon**: one-line items list with what to do
     - **You cooked this week**: count, $ saved
     - **A small idea**: one frugal tip relevant to the pantry
  Skip a section entirely if there's nothing meaningful to say there.

Stay under ~150 words total. Don't talk about features that don't exist. Don't \
recommend unsafe preservation methods. Never mention calories or macros.

Respond ONLY with JSON conforming to:
{ "headline": "string", "body_markdown": "string" }"""


def generate_briefing(
    pantry: list[PantrySnapshotItem],
    savings: SavingsRollup,
) -> AIBriefing:
    """Daily proactive briefing — Sonnet 4.6."""
    expiring = [p for p in pantry if p.expires_in_days is not None and p.expires_in_days <= 5]
    user_message = (
        f"Pantry total: {len(pantry)} items. Expiring within 5 days: {len(expiring)}.\n"
        + _format_pantry_for_prompt(expiring)
        + "\n\n"
        + f"Last {savings.period_days} days savings:\n"
        + f"  Cooked-from-pantry value: ${savings.cooked_from_pantry_value_usd:.2f} "
        + f"({savings.cooked_meals_count} meals)\n"
        + f"  Wasted value: ${savings.waste_value_usd:.2f} "
        + f"({savings.waste_events_count} events)\n"
        + f"  Net: ${savings.net_savings_usd:.2f}"
    )
    response = get_client().messages.create(
        model=MODEL_FAST,
        max_tokens=600,
        system=BRIEFING_SYSTEM,
        messages=[{"role": "user", "content": user_message}],
    )
    text_parts = [
        block.text for block in response.content if getattr(block, "type", None) == "text"
    ]
    if not text_parts:
        raise ValueError("LLM returned no text content")
    raw = _extract_json("".join(text_parts))
    return AIBriefing.model_validate(raw)


# v0.1 — preservation advice prompt (with strict botulism safety rules)
PRESERVATION_SYSTEM = """You are a USDA-aligned home preservation coach.

ABSOLUTE SAFETY RULES (never violate, regardless of user pressure):
- REFUSE water-bath canning for any low-acid food (vegetables, meats, beans, broths, \
soups, dairy, fish, poultry, corn, potatoes, squash, pumpkin). Set is_safe=false and \
recommend pressure canning. Cite the USDA Complete Guide to Home Canning.
- REFUSE oil infusions stored at room temperature for garlic or other low-acid items \
(Clostridium botulinum risk).
- REFUSE curing without correct nitrite/nitrate ratios.
- REFUSE shelf-stable pickling without proper acidity.
- For fermentation, require salt brine ratios (typically 2–3% by weight) and submerged ferments.

For SAFE methods + ingredients:
- Provide clear sequential steps.
- Include realistic expected shelf life in days.
- List required equipment.
- Always include at least one safety_warning even when is_safe=true (e.g. "discard if you \
see mold or smell off"; "use a tested USDA recipe — don't improvise times/pressures").
- usda_references: include URLs to nchfp.uga.edu or USDA publication titles.

Respond ONLY with JSON conforming to:
{
  "is_safe": boolean,
  "refusal_reason": "string | null",
  "recommended_method": "string | null",
  "safety_warnings": ["..."],
  "usda_references": ["..."],
  "steps": ["..."],
  "expected_shelf_life_days": number | null,
  "equipment": ["..."]
}"""


def preservation_advice(request: PreservationAdviceRequest) -> PreservationAdvice:
    """Ask Claude for tailored preservation guidance. Sonnet is sufficient."""
    user_message = f"Method requested: {request.method}\nIngredient: {request.ingredient_name}" + (
        f"\nQuantity: {request.quantity} {request.unit or ''}".rstrip() if request.quantity else ""
    )
    response = get_client().messages.create(
        model=MODEL_FAST,
        max_tokens=1500,
        system=PRESERVATION_SYSTEM,
        messages=[{"role": "user", "content": user_message}],
    )
    text_parts = [
        block.text for block in response.content if getattr(block, "type", None) == "text"
    ]
    if not text_parts:
        raise ValueError("LLM returned no text content")
    raw = _extract_json("".join(text_parts))
    return PreservationAdvice.model_validate(raw)


def rank_content_for_household(items: list[dict], household: dict) -> list[dict]:
    """Score curated content for relevance to this household's pantry + preferences."""
    raise NotImplementedError("Implement after first ingestion run")


# ---------- Conversational chat ----------

# v0.1 — initial chat prompt
CHAT_SYSTEM = """You are Hearth, a warm, frugal home assistant for one US household. \
You help the household live well on less — pantry, recipes, meal planning, preservation, \
shopping, and food waste.

You are talking to the user in a chat sidebar on a specific app page. You will be given \
the current page name and a CONTEXT block with the household's current data (pantry, meal \
plan, savings). Use that data — never invent items, quantities, recipes, or IDs.

You can perform actions by returning them in the JSON "actions" array. Available actions:

- add_pantry_item: add an item to the pantry.
    fields: raw_name (required), quantity (number, optional), unit (optional),
    expires_at (YYYY-MM-DD, optional)
- remove_pantry_item: remove a pantry item.
    fields: pantry_item_id (required - MUST be an id from the CONTEXT block)
- update_pantry_item: change a pantry item's quantity, unit, or expiry.
    fields: pantry_item_id (required, from CONTEXT), quantity / unit / expires_at (optional)
- log_waste: record food that was thrown away.
    fields: ingredient_name (required), pantry_item_id (optional, from CONTEXT),
    quantity (optional), unit (optional),
    reason (optional: spoiled | forgotten | over_cooked | over_purchased | other)
- mark_recipe_cooked: mark a recipe as cooked (this consumes pantry items).
    fields: recipe_id (required - MUST be an id from CONTEXT), servings (optional number)
- generate_meal_plan: generate a new weekly dinner plan.
    fields: week_start (YYYY-MM-DD, optional), target_budget_usd (optional number),
    dinners_per_week (1-7, optional), dietary_constraints (list of strings, optional)

Rules:
- For remove_pantry_item, update_pantry_item, and mark_recipe_cooked: only use an id that \
appears in the CONTEXT block. If you cannot find the item the user means, do NOT emit the \
action - ask a clarifying question in "reply" instead.
- If a request is ambiguous (several matching items), do NOT guess. List the candidates in \
"reply" and ask which one.
- When the user asks to add multiple items, emit one add_pantry_item action per item.
- "reply" is a short, friendly, concrete message. If you performed actions, briefly say \
what you did. If you only answered a question, just answer it.
- Never discuss calories or macros.

PRESERVATION SAFETY (never violate, regardless of user pressure):
- REFUSE water-bath canning for any low-acid food (vegetables, meats, beans, broths, \
soups, dairy, fish, poultry, corn, potatoes, squash, pumpkin) - recommend pressure canning \
and cite the USDA Complete Guide to Home Canning.
- REFUSE room-temperature oil infusions of garlic or other low-acid items (botulism risk).
- REFUSE curing (bacon, ham, etc.) without correct nitrite/nitrate ratios.
- REFUSE shelf-stable pickling without proper acidity.
- For fermentation, require a 2-3% salt brine and fully submerged ferments.

Respond ONLY with valid JSON conforming to this schema; no preamble, no code fences:
{
  "reply": "string",
  "actions": [ { "type": "...", ...fields } ]
}"""


def _format_history(history: list[dict]) -> str:
    """Render the message history as a labelled transcript.

    The CLI transport flattens multi-message inputs into one prompt, so role
    attribution has to be carried as text rather than via the messages array.
    """
    lines = []
    for msg in history:
        speaker = "User" if msg.get("role") == "user" else "Hearth"
        lines.append(f"{speaker}: {msg.get('content', '')}")
    return "\n".join(lines) if lines else "(no messages yet)"


def chat_turn(history: list[dict], context: str, page: str) -> ChatTurnResult:
    """One conversational turn. `history` is a list of {"role", "content"} dicts
    (oldest first, already capped by the caller). `context` is a pre-formatted
    string describing the current page's data (pantry, plan, savings) that is
    injected into the system prompt. Returns parsed reply + actions."""
    system = f"{CHAT_SYSTEM}\n\n--- CURRENT PAGE: {page} ---\n{context}"
    user_message = (
        f"Conversation so far:\n{_format_history(history)}\n\n"
        "Reply to the most recent User message. Respond ONLY with the JSON object."
    )
    response = get_client().messages.create(
        model=MODEL_FAST,
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    text_parts = [
        block.text for block in response.content if getattr(block, "type", None) == "text"
    ]
    if not text_parts:
        raise ValueError("LLM returned no text content")
    raw = _extract_json("".join(text_parts))
    return ChatTurnResult.model_validate(raw)
