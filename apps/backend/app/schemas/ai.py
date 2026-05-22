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
