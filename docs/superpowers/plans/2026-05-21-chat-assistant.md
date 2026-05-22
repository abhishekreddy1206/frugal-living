# Chat Assistant v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the global `ChatSidebar` to a working backend so the Hearth assistant holds a per-page conversation and performs food-tier actions (add/remove/update pantry, log waste, mark cooked, generate a meal plan).

**Architecture:** Actions execute via a prompt-level JSON action protocol — the Claude Code CLI transport cannot do real Anthropic tool-use. Each chat turn is one Sonnet call returning `{reply, actions[]}`; the backend executes the actions against existing food services and emits `core.events`. Each app page gets its own persistent `Conversation` (keyed by `metadata_->>'page'`) with page-specific grounding.

**Tech Stack:** FastAPI / SQLAlchemy 2.0 / PostgreSQL (backend), Next.js 14 / TypeScript (frontend), Claude via the Claude Code CLI through `app/services/llm.py`.

**Spec:** `docs/superpowers/specs/2026-05-21-chat-assistant-design.md`

---

## File structure

| File | Responsibility | Action |
|---|---|---|
| `apps/backend/app/schemas/ai.py` | AI-tier request/response + LLM-output schemas | Create |
| `apps/backend/app/services/pantry.py` | + `add_item` / `soft_delete_item` / `update_item` helpers | Modify |
| `apps/backend/app/services/llm.py` | + `CHAT_SYSTEM` prompt + `chat_turn()` | Modify |
| `apps/backend/app/services/chat.py` | Conversation lookup, page context, action execution, turn orchestration | Create |
| `apps/backend/app/routers/ai.py` | Replace `/conversations` stubs with working endpoints | Modify |
| `apps/web/src/lib/types.ts` | + chat TypeScript types | Modify |
| `apps/web/src/lib/api.ts` | + `openConversation` / `sendChatMessage` | Modify |
| `apps/web/src/components/ChatSidebar.tsx` | Route-aware chat UI wired to the backend | Rewrite |
| `apps/backend/tests/test_chat_*.py` | Unit + endpoint tests | Create |
| `docs/ARCHITECTURE.md`, `CLAUDE.md` | Document new event types + chat status | Modify |

All backend commands run from `apps/backend/`; all frontend commands from `apps/web/`.

---

## Task 1: AI-tier chat schemas

**Files:**
- Create: `apps/backend/app/schemas/ai.py`
- Test: `apps/backend/tests/test_chat_schemas.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_chat_schemas.py`:

```python
"""Tests for the chat schema models."""
from __future__ import annotations

from app.schemas.ai import ChatAction, ChatTurnResult


def test_chat_turn_result_parses_reply_and_actions():
    raw = {"reply": "Added rice.", "actions": [{"type": "add_pantry_item", "raw_name": "rice"}]}
    result = ChatTurnResult.model_validate(raw)
    assert result.reply == "Added rice."
    assert len(result.actions) == 1
    assert result.actions[0].type == "add_pantry_item"
    assert result.actions[0].raw_name == "rice"


def test_chat_turn_result_defaults_empty_actions():
    result = ChatTurnResult.model_validate({"reply": "hello"})
    assert result.actions == []


def test_chat_action_keeps_ids_as_raw_strings():
    """IDs stay strings so a malformed id degrades one action, not the whole turn."""
    action = ChatAction.model_validate(
        {"type": "remove_pantry_item", "pantry_item_id": "not-a-uuid"}
    )
    assert action.pantry_item_id == "not-a-uuid"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_chat_schemas.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.schemas.ai'`.

- [ ] **Step 3: Create the schema module**

Create `apps/backend/app/schemas/ai.py`:

```python
"""AI-tier request/response schemas — chat conversations and turns."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ChatActionType = Literal[
    "add_pantry_item",
    "remove_pantry_item",
    "update_pantry_item",
    "log_waste",
    "mark_recipe_cooked",
    "generate_meal_plan",
]


class ChatAction(BaseModel):
    """One action proposed by the assistant.

    Payload fields are all optional and permissive — this is parsed straight from
    untrusted LLM output. IDs and dates stay as strings so a single malformed
    value degrades that one action rather than failing the whole turn; per-type
    validation happens in the chat service executor.
    """

    type: ChatActionType
    # add / update / remove pantry
    raw_name: str | None = None
    pantry_item_id: str | None = None
    quantity: float | None = None
    unit: str | None = None
    expires_at: str | None = None  # ISO date string
    # log_waste
    ingredient_name: str | None = None
    reason: str | None = None
    # mark_recipe_cooked
    recipe_id: str | None = None
    servings: int | None = None
    # generate_meal_plan
    week_start: str | None = None  # ISO date string
    target_budget_usd: float | None = None
    dinners_per_week: int | None = None
    dietary_constraints: list[str] | None = None


class ChatTurnResult(BaseModel):
    """Parsed LLM output for one chat turn."""

    reply: str = ""
    actions: list[ChatAction] = Field(default_factory=list)


class ActionResult(BaseModel):
    """Outcome of executing one ChatAction — surfaced to the user as a chip."""

    type: str
    status: Literal["ok", "error"]
    summary: str
    error: str | None = None


class ConversationOpenRequest(BaseModel):
    page: str = Field(..., min_length=1, max_length=120)


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    payload: dict[str, Any]
    created_at: datetime


class ConversationOpenResponse(BaseModel):
    conversation_id: uuid.UUID
    page: str
    messages: list[MessageRead]


class ChatMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


class ChatTurnResponse(BaseModel):
    message_id: uuid.UUID
    reply: str
    actions: list[ActionResult]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_chat_schemas.py -v`
Expected: PASS — 3 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/schemas/ai.py apps/backend/tests/test_chat_schemas.py
git commit -m "feat(ai): add chat assistant schemas"
```

---

## Task 2: Pantry mutation helpers

Adds `add_item`, `soft_delete_item`, `update_item` to the pantry service so the chat
executor stays thin and pantry writes live where `consume_for_recipe` / `snapshot_pantry`
already do. The photo-capture endpoint is intentionally left unchanged.

**Files:**
- Modify: `apps/backend/app/services/pantry.py`
- Test: `apps/backend/tests/test_pantry_mutations.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_pantry_mutations.py`:

```python
"""Tests for the chat-facing pantry mutation helpers."""
from __future__ import annotations

import uuid

import pytest

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.core import Event, Household, User
from app.services.pantry import (
    PantryItemNotFound,
    add_item,
    soft_delete_item,
    update_item,
)


def _ctx(db):
    return db.get(Household, DEV_HOUSEHOLD_ID), db.get(User, DEV_USER_ID)


def test_add_item_resolves_ingredient_and_emits_event(db):
    household, user = _ctx(db)
    item = add_item(db, household=household, user=user, raw_name="rice", quantity=2, unit="lb")
    assert item.ingredient_id is not None  # "rice" is a starter ingredient
    assert item.source == "chat"
    events = (
        db.query(Event)
        .filter(Event.event_type == "food.pantry_item.added", Event.entity_id == item.id)
        .all()
    )
    assert len(events) == 1


def test_add_item_projects_expiry_from_shelf_life(db):
    household, user = _ctx(db)
    item = add_item(db, household=household, user=user, raw_name="rice")
    assert item.expires_at is not None  # rice has a 365-day shelf life


def test_soft_delete_item_sets_deleted_at_and_emits(db):
    household, user = _ctx(db)
    item = add_item(db, household=household, user=user, raw_name="quinoa")
    removed = soft_delete_item(db, household=household, user=user, pantry_item_id=item.id)
    assert removed.deleted_at is not None
    events = (
        db.query(Event)
        .filter(Event.event_type == "food.pantry_item.removed", Event.entity_id == item.id)
        .all()
    )
    assert len(events) == 1


def test_soft_delete_item_rejects_unknown_id(db):
    household, user = _ctx(db)
    with pytest.raises(PantryItemNotFound):
        soft_delete_item(db, household=household, user=user, pantry_item_id=uuid.uuid4())


def test_update_item_changes_fields_and_emits(db):
    household, user = _ctx(db)
    item = add_item(db, household=household, user=user, raw_name="eggs", quantity=6, unit="each")
    updated = update_item(
        db, household=household, user=user, pantry_item_id=item.id, quantity=12
    )
    assert float(updated.quantity) == 12.0
    events = (
        db.query(Event)
        .filter(Event.event_type == "food.pantry_item.updated", Event.entity_id == item.id)
        .all()
    )
    assert len(events) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_pantry_mutations.py -v`
Expected: FAIL — `ImportError: cannot import name 'add_item' from 'app.services.pantry'`.

- [ ] **Step 3: Add the helpers to `pantry.py`**

In `apps/backend/app/services/pantry.py`, update the imports at the top of the file. The
current import block is:

```python
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import asc, nulls_last
from sqlalchemy.orm import Session

from app.models.core import Household
from app.models.food import PantryItem, Recipe, RecipeIngredient
from app.schemas.food import PantrySnapshotItem
```

Replace it with:

```python
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import asc, nulls_last
from sqlalchemy.orm import Session

from app.models.core import Household, User
from app.models.food import Ingredient, PantryItem, Recipe, RecipeIngredient
from app.schemas.food import PantrySnapshotItem
from app.services.events import emit_event
from app.services.ingredients import resolve_ingredient
```

Then append to the end of `apps/backend/app/services/pantry.py`:

```python
class PantryItemNotFound(Exception):
    """Raised when a pantry item id can't be resolved for the household."""


def _load_owned_item(
    db: Session, household: Household, pantry_item_id: uuid.UUID
) -> PantryItem:
    item = db.get(PantryItem, pantry_item_id)
    if item is None or item.household_id != household.id or item.deleted_at is not None:
        raise PantryItemNotFound(str(pantry_item_id))
    return item


def add_item(
    db: Session,
    *,
    household: Household,
    user: User,
    raw_name: str,
    quantity: float | None = None,
    unit: str | None = None,
    expires_at: date | None = None,
) -> PantryItem:
    """Create a pantry item from a free-form name: resolve the canonical ingredient,
    fall back to its default unit and shelf-life-projected expiry, emit an event."""
    ingredient_id = resolve_ingredient(db, raw_name)
    ingredient = db.get(Ingredient, ingredient_id) if ingredient_id else None
    resolved_unit = unit or (ingredient.default_unit if ingredient else None)
    resolved_expiry = expires_at
    if resolved_expiry is None and ingredient and ingredient.typical_shelf_life_days:
        resolved_expiry = date.today() + timedelta(days=ingredient.typical_shelf_life_days)

    item = PantryItem(
        household_id=household.id,
        ingredient_id=ingredient_id,
        raw_name=raw_name,
        quantity=quantity,
        unit=resolved_unit,
        expires_at=resolved_expiry,
        source="chat",
    )
    db.add(item)
    db.flush()

    emit_event(
        db,
        event_type="food.pantry_item.added",
        household_id=household.id,
        user_id=user.id,
        entity_type="pantry_item",
        entity_id=item.id,
        payload={
            "raw_name": item.raw_name,
            "quantity": float(item.quantity) if item.quantity is not None else None,
            "unit": item.unit,
            "ingredient_id": str(ingredient_id) if ingredient_id else None,
            "source": "chat",
        },
    )
    return item


def soft_delete_item(
    db: Session,
    *,
    household: Household,
    user: User,
    pantry_item_id: uuid.UUID,
) -> PantryItem:
    """Soft-delete a pantry item (sets deleted_at), emits food.pantry_item.removed."""
    item = _load_owned_item(db, household, pantry_item_id)
    item.deleted_at = datetime.now(UTC)
    db.flush()
    emit_event(
        db,
        event_type="food.pantry_item.removed",
        household_id=household.id,
        user_id=user.id,
        entity_type="pantry_item",
        entity_id=item.id,
        payload={"raw_name": item.raw_name},
    )
    return item


def update_item(
    db: Session,
    *,
    household: Household,
    user: User,
    pantry_item_id: uuid.UUID,
    quantity: float | None = None,
    unit: str | None = None,
    expires_at: date | None = None,
) -> PantryItem:
    """Update supplied fields of a pantry item, emits food.pantry_item.updated."""
    item = _load_owned_item(db, household, pantry_item_id)
    changed: dict[str, object] = {}
    if quantity is not None:
        item.quantity = quantity
        changed["quantity"] = quantity
    if unit is not None:
        item.unit = unit
        changed["unit"] = unit
    if expires_at is not None:
        item.expires_at = expires_at
        changed["expires_at"] = expires_at.isoformat()
    db.flush()
    emit_event(
        db,
        event_type="food.pantry_item.updated",
        household_id=household.id,
        user_id=user.id,
        entity_type="pantry_item",
        entity_id=item.id,
        payload={"raw_name": item.raw_name, "changed": changed},
    )
    return item
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_pantry_mutations.py -v`
Expected: PASS — 5 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/services/pantry.py apps/backend/tests/test_pantry_mutations.py
git commit -m "feat(food): add pantry mutation helpers for the chat assistant"
```

---

## Task 3: `chat_turn` LLM function

**Files:**
- Modify: `apps/backend/app/services/llm.py`
- Test: `apps/backend/tests/test_chat_llm.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_chat_llm.py`:

```python
"""Tests for the chat_turn LLM function."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import llm


def test_chat_turn_parses_reply_and_actions(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    fake.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text",
                text=json.dumps(
                    {
                        "reply": "Added rice to your pantry.",
                        "actions": [{"type": "add_pantry_item", "raw_name": "rice"}],
                    }
                ),
            )
        ]
    )
    result = llm.chat_turn(
        [{"role": "user", "content": "add rice"}], "PANTRY: (empty)", "pantry"
    )
    assert result.reply == "Added rice to your pantry."
    assert result.actions[0].type == "add_pantry_item"
    assert result.actions[0].raw_name == "rice"


def test_chat_turn_handles_fenced_json(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    fake.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text",
                text='```json\n{"reply": "Hi there.", "actions": []}\n```',
            )
        ]
    )
    result = llm.chat_turn([{"role": "user", "content": "hi"}], "", "home")
    assert result.reply == "Hi there."
    assert result.actions == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_chat_llm.py -v`
Expected: FAIL — `AttributeError: module 'app.services.llm' has no attribute 'chat_turn'`.

- [ ] **Step 3: Add the prompt and function to `llm.py`**

In `apps/backend/app/services/llm.py`, add to the schema import block. The current block is:

```python
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
```

Immediately after it, add:

```python
from app.schemas.ai import ChatTurnResult
```

Then append to the end of `apps/backend/app/services/llm.py`:

```python
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
    fields: pantry_item_id (required — MUST be an id from the CONTEXT block)
- update_pantry_item: change a pantry item's quantity, unit, or expiry.
    fields: pantry_item_id (required, from CONTEXT), quantity / unit / expires_at (optional)
- log_waste: record food that was thrown away.
    fields: ingredient_name (required), pantry_item_id (optional, from CONTEXT),
    quantity (optional), unit (optional),
    reason (optional: spoiled | forgotten | over_cooked | over_purchased | other)
- mark_recipe_cooked: mark a recipe as cooked (this consumes pantry items).
    fields: recipe_id (required — MUST be an id from CONTEXT), servings (optional number)
- generate_meal_plan: generate a new weekly dinner plan.
    fields: week_start (YYYY-MM-DD, optional), target_budget_usd (optional number),
    dinners_per_week (1-7, optional), dietary_constraints (list of strings, optional)

Rules:
- For remove_pantry_item, update_pantry_item, and mark_recipe_cooked: only use an id that \
appears in the CONTEXT block. If you cannot find the item the user means, do NOT emit the \
action — ask a clarifying question in "reply" instead.
- If a request is ambiguous (several matching items), do NOT guess. List the candidates in \
"reply" and ask which one.
- When the user asks to add multiple items, emit one add_pantry_item action per item.
- "reply" is a short, friendly, concrete message. If you performed actions, briefly say \
what you did. If you only answered a question, just answer it.
- Never discuss calories or macros.

PRESERVATION SAFETY (never violate, regardless of user pressure):
- REFUSE water-bath canning for any low-acid food (vegetables, meats, beans, broths, \
soups, dairy, fish, poultry, corn, potatoes, squash, pumpkin) — recommend pressure canning \
and cite the USDA Complete Guide to Home Canning.
- REFUSE room-temperature oil infusions of garlic or other low-acid items (botulism risk).
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
    (oldest first, already capped by the caller). Returns parsed reply + actions."""
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_chat_llm.py -v`
Expected: PASS — 2 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/services/llm.py apps/backend/tests/test_chat_llm.py
git commit -m "feat(ai): add chat_turn LLM function"
```

---

## Task 4: Chat orchestration service

**Files:**
- Create: `apps/backend/app/services/chat.py`
- Test: `apps/backend/tests/test_chat_service.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_chat_service.py`:

```python
"""Tests for the chat orchestration service."""
from __future__ import annotations

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.core import Event, Household, User
from app.models.food import PantryItem
from app.schemas.ai import ChatAction, ChatTurnResult
from app.services import chat, llm
from app.services.pantry import add_item


def _ctx(db):
    return db.get(Household, DEV_HOUSEHOLD_ID), db.get(User, DEV_USER_ID)


def test_normalize_page_maps_routes_and_falls_back():
    assert chat.normalize_page("/pantry") == "pantry"
    assert chat.normalize_page("/") == "home"
    assert chat.normalize_page("pantry") == "pantry"
    assert chat.normalize_page("/something-new") == "general"


def test_get_or_create_conversation_is_idempotent_per_page(db):
    household, _ = _ctx(db)
    first = chat.get_or_create_conversation(db, household=household, page="/pantry")
    second = chat.get_or_create_conversation(db, household=household, page="/pantry")
    assert first.id == second.id


def test_get_or_create_conversation_distinct_per_page(db):
    household, _ = _ctx(db)
    pantry = chat.get_or_create_conversation(db, household=household, page="/pantry")
    plan = chat.get_or_create_conversation(db, household=household, page="/plan")
    assert pantry.id != plan.id


def test_build_page_context_includes_pantry_ids(db):
    household, user = _ctx(db)
    item = add_item(db, household=household, user=user, raw_name="rice")
    context = chat.build_page_context(db, household=household, page="pantry")
    assert str(item.id) in context


def test_execute_action_add_pantry_item_creates_row(db):
    household, user = _ctx(db)
    action = ChatAction(type="add_pantry_item", raw_name="lentils", quantity=3, unit="lb")
    result = chat._execute_action(db, household=household, user=user, action=action)
    assert result.status == "ok"
    rows = db.query(PantryItem).filter_by(household_id=household.id).all()
    assert any(r.raw_name == "lentils" for r in rows)


def test_execute_action_remove_with_bad_id_returns_error(db):
    household, user = _ctx(db)
    action = ChatAction(type="remove_pantry_item", pantry_item_id="not-a-uuid")
    result = chat._execute_action(db, household=household, user=user, action=action)
    assert result.status == "error"


def test_run_chat_turn_executes_actions_and_persists(db, monkeypatch):
    household, user = _ctx(db)
    conversation = chat.get_or_create_conversation(db, household=household, page="/pantry")
    monkeypatch.setattr(
        llm,
        "chat_turn",
        lambda history, context, page: ChatTurnResult(
            reply="Added coffee.",
            actions=[ChatAction(type="add_pantry_item", raw_name="coffee")],
        ),
    )
    response = chat.run_chat_turn(
        db, household=household, user=user, conversation=conversation, content="add coffee"
    )
    assert response.reply == "Added coffee."
    assert response.actions[0].status == "ok"
    rows = db.query(PantryItem).filter_by(household_id=household.id).all()
    assert any(r.raw_name == "coffee" for r in rows)
    events = db.query(Event).filter_by(event_type="food.pantry_item.added").all()
    assert len(events) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_chat_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.chat'`.

- [ ] **Step 3: Create the chat service**

Create `apps/backend/app/services/chat.py`:

```python
"""
Chat assistant orchestration.

Conversations are scoped per app page (keyed on metadata->>'page'). Each turn is
one Sonnet call that returns a reply plus a list of actions; actions execute
against the existing food services and emit core.events. The reply states intent;
per-action ActionResults carry the confirmed outcome.
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import asc, nulls_last
from sqlalchemy.orm import Session, selectinload

from app.models.ai import Conversation, Message
from app.models.core import Household, User
from app.models.food import PantryItem, Recipe
from app.schemas.ai import ActionResult, ChatAction, ChatTurnResponse, ChatTurnResult
from app.schemas.food import WasteLogRequest, WeekPlanConstraints
from app.services import llm
from app.services.events import emit_event
from app.services.meal_plans import (
    create_meal_plan_from_ai,
    load_active_plan,
    load_plan_recipes_map,
)
from app.services.pantry import (
    PantryItemNotFound,
    add_item,
    consume_for_recipe,
    snapshot_pantry,
    soft_delete_item,
    update_item,
)
from app.services.waste import log_waste, savings_rollup

logger = logging.getLogger(__name__)

_HISTORY_LIMIT = 20

_ROUTE_TO_PAGE = {
    "/": "home",
    "/pantry": "pantry",
    "/stretch": "stretch",
    "/plan": "plan",
    "/shopping": "shopping",
    "/preservation": "preservation",
    "/waste": "waste",
    "/watch": "watch",
}
_PAGE_KEYS = set(_ROUTE_TO_PAGE.values())


class _ActionError(Exception):
    """A recoverable validation error for a single action."""


# ---------- Page normalization ----------


def normalize_page(raw: str) -> str:
    """Map a route path (or page key) to a known page key; unknown → 'general'."""
    raw = raw.strip()
    if raw in _PAGE_KEYS:
        return raw
    route = raw.rstrip("/") or "/"
    return _ROUTE_TO_PAGE.get(route, "general")


# ---------- Conversations ----------


def get_or_create_conversation(
    db: Session, *, household: Household, page: str
) -> Conversation:
    """Return the household's conversation for `page`, creating it if absent."""
    key = normalize_page(page)
    conv = (
        db.query(Conversation)
        .filter(
            Conversation.household_id == household.id,
            Conversation.deleted_at.is_(None),
            Conversation.metadata_["page"].astext == key,
        )
        .order_by(Conversation.created_at.desc())
        .first()
    )
    if conv is not None:
        return conv
    conv = Conversation(
        household_id=household.id,
        scope="food",
        surface="sidebar",
        title=key.capitalize(),
        metadata_={"page": key},
    )
    db.add(conv)
    db.flush()
    return conv


# ---------- Page context ----------


def _pantry_context(db: Session, household: Household) -> str:
    rows = (
        db.query(PantryItem)
        .filter(PantryItem.household_id == household.id, PantryItem.deleted_at.is_(None))
        .order_by(nulls_last(asc(PantryItem.expires_at)), PantryItem.created_at.desc())
        .all()
    )
    if not rows:
        return "PANTRY: (empty)"
    lines = ["PANTRY (use the id for remove/update/waste actions):"]
    for r in rows:
        qty = f"{r.quantity} {r.unit or ''}".strip() if r.quantity is not None else "qty unknown"
        exp = f", expires {r.expires_at.isoformat()}" if r.expires_at else ""
        lines.append(f"- id={r.id} | {r.raw_name} | {qty}{exp}")
    return "\n".join(lines)


def _plan_context(db: Session, household: Household) -> str:
    plan = load_active_plan(db, household)
    if plan is None:
        return "MEAL PLAN: (no active plan)"
    recipes = load_plan_recipes_map(db, plan)
    lines = [f"ACTIVE MEAL PLAN (week of {plan.week_start.isoformat()}):"]
    for m in sorted(plan.meals, key=lambda x: x.planned_date):
        recipe = recipes.get(m.recipe_id) if m.recipe_id else None
        name = recipe.name if recipe else "(no recipe)"
        rid = f" recipe_id={m.recipe_id}" if m.recipe_id else ""
        lines.append(
            f"- {m.planned_date.isoformat()} {m.meal_type}: {name} (status={m.status}){rid}"
        )
    return "\n".join(lines)


def _savings_context(db: Session, household: Household) -> str:
    r = savings_rollup(db, household=household, period_days=30)
    return (
        f"SAVINGS (last 30 days): cooked-from-pantry ${r.cooked_from_pantry_value_usd:.2f} "
        f"({r.cooked_meals_count} meals), wasted ${r.waste_value_usd:.2f} "
        f"({r.waste_events_count} events), net ${r.net_savings_usd:.2f}."
    )


def build_page_context(db: Session, *, household: Household, page: str) -> str:
    """Assemble the grounding block fed to Claude for a page. The pantry snapshot
    is included everywhere; plan/savings are layered on for the relevant pages."""
    key = normalize_page(page)
    sections = [_pantry_context(db, household)]
    if key in ("plan", "shopping"):
        sections.append(_plan_context(db, household))
    if key in ("home", "waste", "general"):
        sections.append(_savings_context(db, household))
    return "\n\n".join(s for s in sections if s)


# ---------- Action execution ----------


def _parse_uuid(value: str | None, field: str) -> uuid.UUID:
    if not value:
        raise _ActionError(f"missing {field}")
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        raise _ActionError(f"invalid {field}") from None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise _ActionError(f"invalid date {value!r}") from None


def _do_add_pantry_item(
    db: Session, household: Household, user: User, action: ChatAction
) -> ActionResult:
    if not action.raw_name:
        raise _ActionError("missing item name")
    item = add_item(
        db,
        household=household,
        user=user,
        raw_name=action.raw_name,
        quantity=action.quantity,
        unit=action.unit,
        expires_at=_parse_date(action.expires_at),
    )
    return ActionResult(
        type=action.type, status="ok", summary=f"Added {item.raw_name} to your pantry"
    )


def _do_remove_pantry_item(
    db: Session, household: Household, user: User, action: ChatAction
) -> ActionResult:
    pid = _parse_uuid(action.pantry_item_id, "pantry_item_id")
    item = soft_delete_item(db, household=household, user=user, pantry_item_id=pid)
    return ActionResult(
        type=action.type, status="ok", summary=f"Removed {item.raw_name} from your pantry"
    )


def _do_update_pantry_item(
    db: Session, household: Household, user: User, action: ChatAction
) -> ActionResult:
    pid = _parse_uuid(action.pantry_item_id, "pantry_item_id")
    item = update_item(
        db,
        household=household,
        user=user,
        pantry_item_id=pid,
        quantity=action.quantity,
        unit=action.unit,
        expires_at=_parse_date(action.expires_at),
    )
    return ActionResult(type=action.type, status="ok", summary=f"Updated {item.raw_name}")


def _do_log_waste(
    db: Session, household: Household, user: User, action: ChatAction
) -> ActionResult:
    name = action.ingredient_name or action.raw_name
    if not name:
        raise _ActionError("missing ingredient name")
    pid = (
        _parse_uuid(action.pantry_item_id, "pantry_item_id")
        if action.pantry_item_id
        else None
    )
    request = WasteLogRequest(
        pantry_item_id=pid,
        ingredient_name=name,
        quantity=action.quantity,
        unit=action.unit,
        reason=action.reason,
    )
    log_waste(db, household=household, user_id=user.id, request=request)
    return ActionResult(type=action.type, status="ok", summary=f"Logged {name} as waste")


def _do_mark_recipe_cooked(
    db: Session, household: Household, user: User, action: ChatAction
) -> ActionResult:
    rid = _parse_uuid(action.recipe_id, "recipe_id")
    recipe = (
        db.query(Recipe)
        .options(selectinload(Recipe.ingredients))
        .filter(Recipe.id == rid, Recipe.deleted_at.is_(None))
        .one_or_none()
    )
    if recipe is None:
        raise _ActionError("recipe not found")
    servings = action.servings or recipe.servings
    result = consume_for_recipe(
        db, household=household, recipe=recipe, servings_cooked=servings
    )
    emit_event(
        db,
        event_type="food.meal.cooked",
        household_id=household.id,
        user_id=user.id,
        entity_type="recipe",
        entity_id=recipe.id,
        payload={
            "recipe_id": str(recipe.id),
            "recipe_name": recipe.name,
            "servings": servings,
            "cooked_from_pantry_pct": result.cooked_from_pantry_pct,
            "estimated_value_usd": result.estimated_value_usd,
        },
    )
    return ActionResult(
        type=action.type, status="ok", summary=f"Marked {recipe.name} as cooked"
    )


def _do_generate_meal_plan(
    db: Session, household: Household, user: User, action: ChatAction
) -> ActionResult:
    constraints = WeekPlanConstraints(
        week_start=_parse_date(action.week_start) or date.today(),
        target_budget_usd=action.target_budget_usd,
        dinners_per_week=action.dinners_per_week or 7,
        dietary_constraints=action.dietary_constraints or [],
    )
    pantry = snapshot_pantry(db, household)
    ai_plan = llm.generate_weekly_plan(pantry, constraints)
    plan = create_meal_plan_from_ai(
        db, household=household, user=user, ai_plan=ai_plan, constraints=constraints
    )
    return ActionResult(
        type=action.type,
        status="ok",
        summary=f"Generated a {len(ai_plan.meals)}-meal plan for the week of "
        f"{plan.week_start.isoformat()}",
    )


_DISPATCH = {
    "add_pantry_item": _do_add_pantry_item,
    "remove_pantry_item": _do_remove_pantry_item,
    "update_pantry_item": _do_update_pantry_item,
    "log_waste": _do_log_waste,
    "mark_recipe_cooked": _do_mark_recipe_cooked,
    "generate_meal_plan": _do_generate_meal_plan,
}


def _execute_action(
    db: Session, *, household: Household, user: User, action: ChatAction
) -> ActionResult:
    """Execute one action. A failure becomes an error ActionResult — it must never
    abort the turn or block sibling actions."""
    handler = _DISPATCH.get(action.type)
    if handler is None:
        return ActionResult(
            type=action.type,
            status="error",
            summary="Unknown action",
            error=f"unknown action type {action.type}",
        )
    try:
        return handler(db, household, user, action)
    except (PantryItemNotFound, _ActionError) as e:
        return ActionResult(
            type=action.type,
            status="error",
            summary="Couldn't complete that — please try again",
            error=str(e),
        )
    except Exception as e:  # noqa: BLE001 — one bad action must not abort the turn
        logger.exception("chat action %s failed", action.type)
        return ActionResult(
            type=action.type, status="error", summary="That action failed", error=str(e)
        )


# ---------- Turn orchestration ----------


def run_chat_turn(
    db: Session,
    *,
    household: Household,
    user: User,
    conversation: Conversation,
    content: str,
) -> ChatTurnResponse:
    """Persist the user message, call the assistant, execute actions, persist the
    assistant message. The caller is responsible for committing the transaction."""
    # created_at is set explicitly: Postgres func.now() returns the transaction
    # start time, which would tie the user and assistant messages of one turn.
    db.add(
        Message(
            conversation_id=conversation.id,
            role="user",
            content=content,
            payload={},
            created_at=datetime.now(UTC),
        )
    )
    db.flush()

    history_rows = (
        db.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .order_by(asc(Message.created_at))
        .all()
    )
    history = [{"role": m.role, "content": m.content} for m in history_rows][-_HISTORY_LIMIT:]
    page = conversation.metadata_.get("page", "general")
    context = build_page_context(db, household=household, page=page)

    try:
        turn = llm.chat_turn(history, context, page)
    except Exception:  # noqa: BLE001 — LLM output is untrusted; degrade gracefully
        logger.exception("chat_turn failed for conversation %s", conversation.id)
        turn = ChatTurnResult(
            reply="I had trouble with that — could you rephrase?", actions=[]
        )

    results = [
        _execute_action(db, household=household, user=user, action=a) for a in turn.actions
    ]

    assistant_msg = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=turn.reply,
        payload={
            "actions": [a.model_dump(mode="json") for a in turn.actions],
            "results": [r.model_dump(mode="json") for r in results],
        },
        created_at=datetime.now(UTC),
    )
    db.add(assistant_msg)
    db.flush()

    return ChatTurnResponse(
        message_id=assistant_msg.id, reply=turn.reply, actions=results
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_chat_service.py -v`
Expected: PASS — 7 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/services/chat.py apps/backend/tests/test_chat_service.py
git commit -m "feat(ai): add chat orchestration service"
```

---

## Task 5: Wire the conversation endpoints

**Files:**
- Modify: `apps/backend/app/routers/ai.py`
- Test: `apps/backend/tests/test_chat_endpoints.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_chat_endpoints.py`:

```python
"""End-to-end tests for the chat conversation endpoints."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import DEV_HOUSEHOLD_ID
from app.db import SessionLocal
from app.main import app
from app.models.core import Event
from app.models.food import PantryItem
from app.schemas.ai import ChatAction, ChatTurnResult
from app.services import llm


@pytest.fixture
def client():
    return TestClient(app)


def test_open_conversation_creates_thread(client):
    resp = client.post("/api/v1/ai/conversations", json={"page": "/pantry"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["page"] == "pantry"
    assert body["messages"] == []
    assert uuid.UUID(body["conversation_id"])


def test_open_conversation_idempotent_per_page(client):
    first = client.post("/api/v1/ai/conversations", json={"page": "/pantry"}).json()
    second = client.post("/api/v1/ai/conversations", json={"page": "/pantry"}).json()
    assert first["conversation_id"] == second["conversation_id"]


def test_post_message_runs_turn_and_persists(client, monkeypatch):
    monkeypatch.setattr(
        llm,
        "chat_turn",
        lambda history, context, page: ChatTurnResult(
            reply="Added rice to your pantry.",
            actions=[ChatAction(type="add_pantry_item", raw_name="rice")],
        ),
    )
    conv = client.post("/api/v1/ai/conversations", json={"page": "/pantry"}).json()
    resp = client.post(
        f"/api/v1/ai/conversations/{conv['conversation_id']}/messages",
        json={"content": "add rice"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reply"] == "Added rice to your pantry."
    assert body["actions"][0]["status"] == "ok"

    with SessionLocal() as db:
        items = db.query(PantryItem).filter_by(household_id=DEV_HOUSEHOLD_ID).all()
        assert any(i.raw_name == "rice" for i in items)
        events = db.query(Event).filter_by(event_type="food.pantry_item.added").all()
        assert len(events) == 1

    # Re-opening the page returns the persisted turn.
    reopened = client.post("/api/v1/ai/conversations", json={"page": "/pantry"}).json()
    assert len(reopened["messages"]) == 2


def test_post_message_404_for_missing_conversation(client):
    resp = client.post(
        f"/api/v1/ai/conversations/{uuid.uuid4()}/messages",
        json={"content": "hi"},
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_chat_endpoints.py -v`
Expected: FAIL — the stub `POST /conversations` returns `{"conversation": None, ...}`, so `body["page"]` raises `KeyError` / assertions fail.

- [ ] **Step 3: Add conversation cleanup to `conftest.py`**

The chat endpoint tests commit (via `TestClient`), and `conftest.py`'s per-test
`_clean_household_data` fixture does not currently wipe `ai.conversations` / `ai.messages` —
so conversations would leak between tests. Fix it once, globally.

In `apps/backend/tests/conftest.py`, change the model import:

```python
from app.models.ai import Briefing
```

to:

```python
from app.models.ai import Briefing, Conversation
```

Then in the `_clean_household_data` fixture body, add this line immediately before the
existing `db_.query(Event)...` delete:

```python
        db_.query(Conversation).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
```

`ai.messages` rows cascade-delete via the `messages.conversation_id` FK (`ondelete="CASCADE"`).

- [ ] **Step 4: Replace the conversation stubs in `ai.py`**

In `apps/backend/app/routers/ai.py`, update the imports. The current import block is:

```python
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import CurrentHousehold, CurrentUser
from app.db import get_db
from app.models.ai import Briefing
from app.schemas.food import BriefingRead
from app.services.briefings import (
    get_or_generate_today,
    get_today,
    mark_read,
)
```

Replace it with:

```python
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import asc
from sqlalchemy.orm import Session

from app.auth import CurrentHousehold, CurrentUser
from app.db import get_db
from app.models.ai import Briefing, Conversation, Message
from app.schemas.ai import (
    ChatMessageRequest,
    ChatTurnResponse,
    ConversationOpenRequest,
    ConversationOpenResponse,
    MessageRead,
)
from app.schemas.food import BriefingRead
from app.services.briefings import (
    get_or_generate_today,
    get_today,
    mark_read,
)
from app.services.chat import get_or_create_conversation, run_chat_turn
```

Then replace the entire `# ---------- Conversations (chat sidebar) — stubs ----------` section
(the four functions `list_conversations`, `create_conversation`, `list_messages`,
`post_message`) with:

```python
# ---------- Conversations (chat sidebar) ----------


@router.post("/conversations", response_model=ConversationOpenResponse)
def open_conversation(
    request: ConversationOpenRequest,
    household: CurrentHousehold,
    db: Annotated[Session, Depends(get_db)],
) -> ConversationOpenResponse:
    """Get-or-create the conversation for a page and return its message history."""
    conv = get_or_create_conversation(db, household=household, page=request.page)
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conv.id)
        .order_by(asc(Message.created_at))
        .all()
    )
    db.commit()
    return ConversationOpenResponse(
        conversation_id=conv.id,
        page=conv.metadata_.get("page", "general"),
        messages=[MessageRead.model_validate(m) for m in messages],
    )


@router.post("/conversations/{conv_id}/messages", response_model=ChatTurnResponse)
def post_message(
    conv_id: uuid.UUID,
    request: ChatMessageRequest,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ChatTurnResponse:
    """Run one chat turn: persist the message, call the assistant, execute actions."""
    conv = db.get(Conversation, conv_id)
    if conv is None or conv.household_id != household.id or conv.deleted_at is not None:
        raise HTTPException(404, "conversation not found")
    response = run_chat_turn(
        db, household=household, user=user, conversation=conv, content=request.content
    )
    db.commit()
    return response


@router.get("/conversations")
def list_conversations(db: Annotated[Session, Depends(get_db)]):
    """Conversation-list view. Stub — no thread-list UI in v1."""
    return {"conversations": [], "todo": "List recent Conversation rows for household"}
```

(The `GET /conversations/{conv_id}/messages` stub is dropped — history is returned by
`POST /conversations`. The voice and briefing sections of the file are unchanged.)

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_chat_endpoints.py -v`
Expected: PASS — 4 tests.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/routers/ai.py apps/backend/tests/test_chat_endpoints.py apps/backend/tests/conftest.py
git commit -m "feat(ai): wire chat conversation endpoints"
```

---

## Task 6: Frontend chat types + API client

**Files:**
- Modify: `apps/web/src/lib/types.ts`
- Modify: `apps/web/src/lib/api.ts`

- [ ] **Step 1: Add the chat types**

Append to `apps/web/src/lib/types.ts`:

```typescript
// ---------- Chat assistant ----------

export interface ActionResult {
  type: string;
  status: "ok" | "error";
  summary: string;
  error: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface ConversationOpenResponse {
  conversation_id: string;
  page: string;
  messages: ChatMessage[];
}

export interface ChatTurnResponse {
  message_id: string;
  reply: string;
  actions: ActionResult[];
}
```

- [ ] **Step 2: Add the API client functions**

In `apps/web/src/lib/api.ts`, add `ChatTurnResponse` and `ConversationOpenResponse` to the
import block from `./types` (keep the existing imports, add these two names alphabetically).

Then append to the end of `apps/web/src/lib/api.ts`:

```typescript
// ---------- Chat assistant ----------

export function openConversation(page: string): Promise<ConversationOpenResponse> {
  return api<ConversationOpenResponse>("/api/v1/ai/conversations", {
    method: "POST",
    body: JSON.stringify({ page }),
  });
}

export function sendChatMessage(
  conversationId: string,
  content: string,
): Promise<ChatTurnResponse> {
  return api<ChatTurnResponse>(
    `/api/v1/ai/conversations/${conversationId}/messages`,
    { method: "POST", body: JSON.stringify({ content }) },
  );
}
```

- [ ] **Step 3: Verify the frontend typechecks**

Run (from `apps/web/`): `pnpm typecheck`
Expected: PASS — no type errors.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/lib/types.ts apps/web/src/lib/api.ts
git commit -m "feat(web): add chat API client and types"
```

---

## Task 7: Wire `ChatSidebar` to the backend

Rewrites the component so it is route-aware, loads the current page's conversation, sends
real messages, shows an in-flight state, and renders action results as chips.

**Files:**
- Rewrite: `apps/web/src/components/ChatSidebar.tsx`

- [ ] **Step 1: Replace the component**

Overwrite `apps/web/src/components/ChatSidebar.tsx` with:

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { openConversation, sendChatMessage } from "@/lib/api";
import type { ActionResult } from "@/lib/types";

type Msg = {
  role: "user" | "assistant";
  content: string;
  actions?: ActionResult[];
};

const GREETING =
  "Hi, I'm Hearth. I can add things to your pantry, plan meals, log waste, and answer " +
  "questions about what you have. What do you need?";

function Flame({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} fill="currentColor" aria-hidden>
      <path d="M8 2C5 5 4 7 4 9.2A4 4 0 0 0 12 9.2C12 7 11 5 8 2Z" />
    </svg>
  );
}

/**
 * Always-available Hearth chat. Collapsed to a pill by default. The conversation
 * is scoped to the current page — navigating swaps to that page's thread.
 */
export default function ChatSidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [convId, setConvId] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load (or create) the conversation for the current page whenever the sidebar
  // is open and the route changes.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setConvId(null);
    setError(null);
    openConversation(pathname)
      .then((res) => {
        if (cancelled) return;
        setConvId(res.conversation_id);
        setMsgs(
          res.messages.map((m) => ({
            role: m.role,
            content: m.content,
            actions: (m.payload?.results as ActionResult[] | undefined) ?? undefined,
          })),
        );
      })
      .catch(() => {
        if (!cancelled) setError("Couldn't load the assistant.");
      });
    return () => {
      cancelled = true;
    };
  }, [open, pathname]);

  const send = useCallback(async () => {
    const text = draft.trim();
    if (!text || !convId || busy) return;
    setDraft("");
    setError(null);
    setMsgs((m) => [...m, { role: "user", content: text }]);
    setBusy(true);
    try {
      const res = await sendChatMessage(convId, text);
      setMsgs((m) => [
        ...m,
        { role: "assistant", content: res.reply, actions: res.actions },
      ]);
    } catch {
      setError("Something went wrong. Try again.");
    } finally {
      setBusy(false);
    }
  }, [draft, convId, busy]);

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 z-40 flex items-center gap-2 rounded-full bg-clay px-5 py-3 text-sm font-semibold text-paper shadow-warm-lg transition hover:bg-clay-deep"
      >
        <Flame className="h-4 w-4" />
        Ask Hearth
      </button>
    );
  }

  return (
    <aside className="fixed right-0 top-0 z-40 flex h-screen w-[348px] flex-col border-l border-line bg-raised shadow-warm-lg">
      <header className="flex items-center justify-between border-b border-line px-5 py-4">
        <div className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-clay text-paper">
            <Flame className="h-3.5 w-3.5" />
          </span>
          <div className="leading-tight">
            <div className="font-display text-[17px] font-semibold text-ink">
              Hearth chat
            </div>
            <div className="text-[11px] text-ink-faint">Knows this page&apos;s context</div>
          </div>
        </div>
        <button
          onClick={() => setOpen(false)}
          className="grid h-7 w-7 place-items-center rounded-md text-ink-faint transition hover:bg-paper hover:text-ink"
          aria-label="Close chat"
        >
          ✕
        </button>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
        {msgs.length === 0 && (
          <div className="mr-8 rounded-2xl rounded-bl-sm border border-line bg-paper px-3.5 py-2.5 text-sm text-ink">
            {GREETING}
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i}>
            <div
              className={
                m.role === "user"
                  ? "ml-8 rounded-2xl rounded-br-sm bg-clay px-3.5 py-2.5 text-sm text-paper"
                  : "mr-8 rounded-2xl rounded-bl-sm border border-line bg-paper px-3.5 py-2.5 text-sm text-ink"
              }
            >
              {m.content}
            </div>
            {m.actions && m.actions.length > 0 && (
              <div className="mr-8 mt-1.5 flex flex-wrap gap-1.5">
                {m.actions.map((a, j) => (
                  <span
                    key={j}
                    className={
                      a.status === "ok"
                        ? "rounded-full border border-line bg-paper px-2 py-0.5 text-[11px] text-ink-faint"
                        : "rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[11px] text-amber-800"
                    }
                  >
                    {a.status === "ok" ? "✓" : "⚠"} {a.summary}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && (
          <div className="mr-8 rounded-2xl rounded-bl-sm border border-line bg-paper px-3.5 py-2.5 text-sm text-ink-faint">
            Hearth is thinking…
          </div>
        )}
        {error && <div className="text-[12px] text-amber-800">{error}</div>}
      </div>

      <form
        className="flex gap-2 border-t border-line px-4 py-3"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={convId ? "Ask anything…" : "Loading…"}
          disabled={!convId || busy}
          className="flex-1 rounded-lg border border-line bg-paper px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-clay focus:outline-none disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={!convId || busy || !draft.trim()}
          className="rounded-lg bg-ink px-3.5 py-2 text-sm font-semibold text-paper transition hover:bg-clay disabled:opacity-50"
        >
          Send
        </button>
      </form>

      <p className="px-5 pb-3 text-[11px] text-ink-faint">
        Voice (&ldquo;hey Hearth&rdquo;) — wired in an upcoming sprint.
      </p>
    </aside>
  );
}
```

- [ ] **Step 2: Verify the frontend typechecks**

Run (from `apps/web/`): `pnpm typecheck`
Expected: PASS — no type errors.

- [ ] **Step 3: Manual smoke test**

Start the stack: `./frugal up` (from the repo root). In the browser at `http://localhost:3000`:
- Click "Ask Hearth" on `/pantry`; confirm the greeting shows and the input enables.
- Send "add rice, quinoa, and coffee to the pantry"; confirm a reply plus ✓ chips appear,
  and the items show on the `/pantry` page after refresh.
- Navigate to `/plan` with the sidebar open; confirm the thread swaps (empty/own history).
- Send a question like "what's expiring soon?"; confirm a grounded text answer with no chips.

Record the outcome. If anything fails, debug before committing.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/ChatSidebar.tsx
git commit -m "feat(web): wire ChatSidebar to the chat backend"
```

---

## Task 8: Full verification

**Files:** none (verification only — commit only if fixes are needed).

- [ ] **Step 1: Run the full backend test suite**

Run (from `apps/backend/`): `uv run pytest`
Expected: PASS — all prior tests plus the new `test_chat_*` and `test_pantry_mutations`
tests (134 existing + ~21 new ≈ 155). If anything fails, fix it and re-run.

- [ ] **Step 2: Lint and type-check the backend**

Run (from `apps/backend/`): `uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: PASS — no lint or type errors. Fix any reported issues (commonly: import
ordering, an unused import, or a missing type annotation in `chat.py`).

- [ ] **Step 3: Type-check the frontend**

Run (from `apps/web/`): `pnpm typecheck`
Expected: PASS — no type errors.

- [ ] **Step 4: Commit any fixes**

If steps 1-3 required changes:

```bash
git add -A
git commit -m "fix: address verification findings for the chat assistant"
```

If nothing needed fixing, skip the commit.

---

## Task 9: Documentation

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Document the new event types**

In `docs/ARCHITECTURE.md`, find the event-types section (the events.py docstring points to
"§5.5"). Add `food.pantry_item.removed` and `food.pantry_item.updated` to the documented
event-type list, alongside the existing `food.pantry_item.added` / `food.pantry_item.wasted`
entries, noting they are emitted by chat-driven pantry edits.

- [ ] **Step 2: Update the project status in `CLAUDE.md`**

In `CLAUDE.md` (the `frugal-living` one), update the "Current state" section:
- Move conversational chat out of the "still stubbed" list.
- Under "What's fully implemented", add a line to the `ai` entry, e.g.:
  `**`ai`** — daily briefings (Sprint 7); conversational chat assistant with per-page
  context and food-tier actions (add/remove/update pantry, log waste, mark cooked,
  generate meal plan). Voice is still a stub.`
- In the stubbed list, keep only `/voice/*` and `GET /conversations` (thread list) under `ai`.

- [ ] **Step 3: Commit**

```bash
git add docs/ARCHITECTURE.md CLAUDE.md
git commit -m "docs: note chat assistant and new pantry event types"
```

---

## Self-review notes

- **Spec coverage:** action protocol → Tasks 1,3,4; six actions → Task 4 `_DISPATCH`;
  per-page context + `metadata_->>'page'` keying → Task 4; no migration → confirmed
  (`ai.conversations`/`ai.messages` exist in `0002`); endpoints → Task 5; error handling
  (graceful LLM fallback, per-action errors, 404) → Tasks 4,5; frontend → Tasks 6,7;
  testing → every backend task; new event types → Tasks 2,9.
- **Transport constraint:** `chat_turn` flattens history into one labelled prompt because
  the CLI shim collapses the messages array — handled in Task 3.
- **Permissive LLM parsing:** `ChatAction` keeps IDs/dates as strings (Task 1) so a single
  malformed value yields one error chip rather than failing the whole turn.
- **Known tradeoff:** `generate_meal_plan` runs a synchronous Opus call inside the turn —
  the "Hearth is thinking…" state covers it; async generation is explicitly out of scope.
