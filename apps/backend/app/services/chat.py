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
from app.models.community import CommunityItem
from app.models.core import Household, User
from app.models.food import PantryItem, Recipe
from app.schemas.ai import ActionResult, ChatAction, ChatTurnResponse, ChatTurnResult
from app.schemas.food import WasteLogRequest, WeekPlanConstraints
from app.services import llm
from app.services.community import items as community_items
from app.services.community.items import CommunityItemNotFound
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
    "/inventory": "inventory",
    "/watch": "watch",
}
_PAGE_KEYS = set(_ROUTE_TO_PAGE.values())


class _ActionError(Exception):
    """A recoverable validation error for a single action."""


# ---------- Page normalization ----------


def normalize_page(raw: str) -> str:
    """Map a route path (or page key) to a known page key; unknown -> 'general'."""
    raw = raw.strip()
    if raw in _PAGE_KEYS:
        return raw
    route = raw.rstrip("/") or "/"
    return _ROUTE_TO_PAGE.get(route, "general")


# ---------- Conversations ----------


def _scope_for_page(page_key: str) -> str:
    """The conversation scope for a page key: inventory is Tier B, the rest food."""
    return "community" if page_key == "inventory" else "food"


def get_or_create_conversation(db: Session, *, household: Household, page: str) -> Conversation:
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
        scope=_scope_for_page(key),
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


def _inventory_context(db: Session, household: Household) -> str:
    rows = (
        db.query(CommunityItem)
        .filter(
            CommunityItem.household_id == household.id,
            CommunityItem.deleted_at.is_(None),
        )
        .order_by(CommunityItem.created_at.desc())
        .all()
    )
    if not rows:
        return "INVENTORY: (empty)"
    lines = ["INVENTORY (use the id for update/remove actions):"]
    for r in rows:
        qty = f" x{r.quantity}" if r.quantity and r.quantity > 1 else ""
        tags = f" [{', '.join(r.tags)}]" if r.tags else ""
        loc = f" · {r.location}" if r.location else ""
        cond = f" · {r.condition}" if r.condition else ""
        lines.append(f"- id={r.id} | {r.name}{qty} | {r.category}{tags}{loc}{cond}")
    return "\n".join(lines)


def build_page_context(db: Session, *, household: Household, page: str) -> str:
    """Assemble the grounding block fed to Claude for a page. The inventory page
    (Tier B) is grounded in inventory only; food pages get pantry plus, where
    relevant, the meal plan and savings."""
    key = normalize_page(page)
    if key == "inventory":
        return _inventory_context(db, household)
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
    pid = _parse_uuid(action.pantry_item_id, "pantry_item_id") if action.pantry_item_id else None
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
    result = consume_for_recipe(db, household=household, recipe=recipe, servings_cooked=servings)
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
    return ActionResult(type=action.type, status="ok", summary=f"Marked {recipe.name} as cooked")


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


def _do_add_inventory_item(
    db: Session, household: Household, user: User, action: ChatAction
) -> ActionResult:
    if not action.raw_name:
        raise _ActionError("missing item name")
    quantity = int(action.quantity) if action.quantity is not None else 1
    item = community_items.create_item(
        db,
        household=household,
        user=user,
        name=action.raw_name,
        category=action.category or "other",
        tags=action.tags or [],
        quantity=quantity,
        condition=action.condition,
        estimated_value_usd=action.estimated_value_usd,
        location=action.location,
        source="chat",
    )
    return ActionResult(
        type=action.type, status="ok", summary=f"Added {item.name} to your inventory"
    )


def _do_update_inventory_item(
    db: Session, household: Household, user: User, action: ChatAction
) -> ActionResult:
    iid = _parse_uuid(action.inventory_item_id, "inventory_item_id")
    quantity = int(action.quantity) if action.quantity is not None else None
    try:
        item = community_items.update_item(
            db,
            household=household,
            user=user,
            item_id=iid,
            name=action.raw_name,
            category=action.category,
            tags=action.tags,
            quantity=quantity,
            condition=action.condition,
            estimated_value_usd=action.estimated_value_usd,
            location=action.location,
        )
    except CommunityItemNotFound:
        raise _ActionError("inventory item not found") from None
    return ActionResult(type=action.type, status="ok", summary=f"Updated {item.name}")


def _do_remove_inventory_item(
    db: Session, household: Household, user: User, action: ChatAction
) -> ActionResult:
    iid = _parse_uuid(action.inventory_item_id, "inventory_item_id")
    try:
        item = community_items.soft_delete_item(
            db, household=household, user=user, item_id=iid
        )
    except CommunityItemNotFound:
        raise _ActionError("inventory item not found") from None
    return ActionResult(
        type=action.type, status="ok", summary=f"Removed {item.name} from your inventory"
    )


_DISPATCH = {
    "add_pantry_item": _do_add_pantry_item,
    "remove_pantry_item": _do_remove_pantry_item,
    "update_pantry_item": _do_update_pantry_item,
    "log_waste": _do_log_waste,
    "mark_recipe_cooked": _do_mark_recipe_cooked,
    "generate_meal_plan": _do_generate_meal_plan,
    "add_inventory_item": _do_add_inventory_item,
    "update_inventory_item": _do_update_inventory_item,
    "remove_inventory_item": _do_remove_inventory_item,
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
        turn = ChatTurnResult(reply="I had trouble with that — could you rephrase?", actions=[])

    results = [_execute_action(db, household=household, user=user, action=a) for a in turn.actions]

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

    return ChatTurnResponse(message_id=assistant_msg.id, reply=turn.reply, actions=results)
