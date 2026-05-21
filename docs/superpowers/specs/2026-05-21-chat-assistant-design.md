# Chat Assistant v1 — Design Spec

**Date:** 2026-05-21
**Status:** Approved for planning
**Scope:** Wire the global `ChatSidebar` to a working backend so the assistant can hold a
conversation and perform food-tier actions (add/remove/update pantry, log waste, mark
cooked, generate a meal plan), with a separate persistent conversation thread per page.

---

## 1. Problem

The `ChatSidebar` component (mounted globally in `apps/web/src/app/layout.tsx`) looks
finished but is a pure UI stub: its `send()` function never calls the backend — it appends
a hardcoded "not wired up yet" reply. The backend `/api/v1/ai/conversations/*` endpoints in
`apps/backend/app/routers/ai.py` are likewise stubs returning `{"todo": ...}` placeholder
JSON. No commit ever wired chat up.

This spec defines v1: a working conversational assistant that can both answer questions
grounded in household data and execute food-tier actions.

## 2. Key constraint — no real tool use

The LLM transport is the Claude Code CLI (`claude -p`), wrapped by `_CliMessages` in
`app/services/llm.py`. That shim is text-in/text-out only: it silently drops any `tools=`
argument and cannot run the Anthropic `tool_use`/`tool_result` loop against our in-process
database. Switching to the Anthropic SDK would require an `ANTHROPIC_API_KEY` we do not
have and would break the CLI-transport status quo.

**Therefore actions execute via a prompt-level JSON action protocol**, consistent with how
every other function in `llm.py` already works (structured-JSON prompt + `_extract_json` +
Pydantic validation). One LLM call per turn.

## 3. Action protocol

Each turn, Claude is instructed to return exactly one JSON object:

```json
{
  "reply": "string — the message shown to the user",
  "actions": [ { "type": "...", ...payload } ]
}
```

The backend parses it, executes each action against existing services, and returns
Claude's `reply` plus a structured list of per-action results. The frontend renders the
results as confirmation chips so the user sees the confirmed outcome even though Claude's
`reply` is written before execution (it states intent).

When `actions` is empty the turn is plain Q&A.

### Action catalog (v1)

All actions are available on every page — the page sets *context*, not *capability*.

| `type` | Payload fields | Executes via | Event emitted |
|---|---|---|---|
| `add_pantry_item` | `raw_name` (req), `quantity?`, `unit?`, `expires_at?` | `services.pantry.add_item` | `food.pantry_item.added` |
| `remove_pantry_item` | `pantry_item_id` (req) | `services.pantry.soft_delete_item` | `food.pantry_item.removed` *(new type)* |
| `update_pantry_item` | `pantry_item_id` (req), `quantity?`, `unit?`, `expires_at?` | `services.pantry.update_item` | `food.pantry_item.updated` *(new type)* |
| `log_waste` | `pantry_item_id?`, `ingredient_name` (req), `quantity?`, `unit?`, `reason?` | `services.waste.log_waste` | `food.pantry_item.wasted` (service emits) |
| `mark_recipe_cooked` | `recipe_id` (req), `servings?` | `services.pantry.consume_for_recipe` | `food.meal.cooked` |
| `generate_meal_plan` | `week_start?`, `target_budget_usd?`, `dinners_per_week?`, `dietary_constraints?` | `services.llm.generate_weekly_plan` + `services.meal_plans.create_meal_plan_from_ai` | (service emits) |

Rules baked into the system prompt:

- For `remove_pantry_item`, `update_pantry_item`, `mark_recipe_cooked`: the ID **must**
  come from the page-context grounding block. Never invent an ID.
- If a request is ambiguous ("remove the milk" with three milk items in context), Claude
  must **not** emit the action — it asks a clarifying question in `reply`, listing the
  candidates. Disambiguation is conversational; no special backend logic.
- `generate_meal_plan` with no `week_start` defaults to today's date.
- Preservation safety rules carry over verbatim from `PRESERVATION_SYSTEM` (refuse
  low-acid water-bath canning, room-temp garlic oil infusions, etc.) — chat can be asked
  canning questions, especially on `/preservation`.
- Never discuss macros/calories (consistent with the rest of the product).

## 4. Per-page context

Each page route gets its own `Conversation`, keyed by `household_id` plus
`metadata_->>'page'` (rule #3: page identity lives in the JSONB `metadata_` column, DB
column `metadata`). Opening the sidebar on a route loads-or-creates that page's thread;
navigating to another route swaps to that route's thread.

The page also determines the **grounding** assembled into the LLM context block:

| Route | `page` key | Grounding fed to Claude |
|---|---|---|
| `/` | `home` | compact pantry + savings rollup + active-plan summary |
| `/pantry` | `pantry` | full pantry snapshot **with item IDs** |
| `/stretch` | `stretch` | pantry snapshot |
| `/plan` | `plan` | pantry + active meal plan (planned-meal IDs + recipe IDs) |
| `/shopping` | `shopping` | active shopping list + active plan |
| `/preservation` | `preservation` | pantry snapshot (expiring items emphasized) |
| `/waste` | `waste` | pantry + savings rollup |
| `/watch` | `watch` | content feed item titles |

A compact pantry snapshot **with item IDs** is included on every page (it is small and the
most-referenced entity, and lets ID-based actions resolve from any page). Page-specific
extras layer on top.

Unknown / future routes do **not** error — they fall back to a `general` grounding
(home-like) and a conversation keyed by the raw path. Only an empty page string is a 400.

## 5. Data model

No migration. `ai.conversations` and `ai.messages` already exist (migration
`0002_create_all_tables`). Usage:

- `Conversation.metadata_` = `{"page": "<page key>"}` for per-page lookup.
- `Conversation.scope` = `"food"`, `Conversation.surface` = `"sidebar"`.
- `Conversation.title` = a short human label (e.g. `"Pantry"`); optional, cosmetic.
- `Message.role` = `"user"` | `"assistant"`.
- `Message.content` = the text (`reply` for assistant messages).
- `Message.payload` (assistant messages) = `{"actions": [...], "results": [...]}`.

No new index — at v1 volume (one household, ~8 pages) filtering by `household_id` and
scanning a handful of rows for the `page` match is trivial.

New `core.events` event types introduced: `food.pantry_item.removed`,
`food.pantry_item.updated`. `food.pantry_item.added`, `food.pantry_item.wasted`, and
`food.meal.cooked` already exist and are reused, so streaks / savings / briefings pick up
chat-driven mutations with no extra work.

## 6. API surface (`app/routers/ai.py`)

Replaces the `/conversations` stubs. Briefing and voice endpoints are untouched.

### `POST /api/v1/ai/conversations`
Open (get-or-create) the conversation for a page and return its history.
- Request: `{ "page": "<route path or page key>" }`
- Response: `{ "conversation_id": "uuid", "page": "<normalized key>", "messages": [MessageRead, ...] }`

### `POST /api/v1/ai/conversations/{id}/messages`
Run one chat turn.
- Request: `{ "content": "string" }`
- Behaviour: load conversation (404 if missing / wrong household) → persist the user
  message → build page grounding → call `llm.chat_turn` → execute actions → persist the
  assistant message (with `actions`/`results` in `payload`) → return.
- Response: `{ "message_id": "uuid", "reply": "string", "actions": [ActionResult, ...] }`

### `GET /api/v1/ai/conversations` — remains a stub
No conversation-list UI in v1; this is genuinely future scope.

### `GET /api/v1/ai/conversations/{id}/messages` — remains a stub
History is returned by `POST /conversations`; a standalone GET is not needed in v1.

## 7. New code

### `app/schemas/ai.py` *(new file)*
Pydantic request/response + LLM-output models:
- `ChatAction` — `type: Literal[...]` plus all-optional payload fields; permissive shape
  for defensive parsing of LLM JSON, validated per-type in the executor.
- `ChatTurnResult` — LLM output: `reply: str`, `actions: list[ChatAction]`.
- `ActionResult` — `type: str`, `status: Literal["ok", "error"]`, `summary: str`,
  `error: str | None`.
- `ConversationOpenRequest` (`page`), `ConversationOpenResponse`
  (`conversation_id`, `page`, `messages`).
- `ChatMessageRequest` (`content`), `ChatTurnResponse`
  (`message_id`, `reply`, `actions`).
- `MessageRead` — `id`, `role`, `content`, `payload`, `created_at`.

### `app/services/chat.py` *(new file)*
- `get_or_create_conversation(db, household, page) -> Conversation`
- `build_page_context(db, household, page) -> str` — assembles the grounding text for the
  page (table in §4). Page key whitelist defined here; unknown → `general`.
- `run_chat_turn(db, household, user, conversation, content) -> ChatTurnResponse` —
  orchestration: persist user message, build context, call `llm.chat_turn`, dispatch each
  action, persist assistant message, return.
- `_execute_action(db, household, user, action) -> ActionResult` — dispatch on
  `action.type`; each branch calls the relevant service and builds a deterministic,
  templated `summary` (e.g. `"Added rice to your pantry"`, `"Removed Milk"`). Per-action
  failures (bad/missing ID, wrong household) produce `status="error"` results; they do not
  abort the turn or other actions.

### `app/services/pantry.py` *(extend)*
Add pantry-mutation helpers so the chat executor stays thin and pantry writes live in the
pantry service (where `consume_for_recipe` / `snapshot_pantry` already live):
- `add_item(db, *, household, user, raw_name, quantity, unit, expires_at) -> PantryItem` —
  resolves the ingredient, applies default-unit and shelf-life-projected expiry fallbacks,
  creates the row with `source="chat"`, emits `food.pantry_item.added`.
- `soft_delete_item(db, *, household, user, pantry_item_id) -> PantryItem` — sets
  `deleted_at`, emits `food.pantry_item.removed`. Raises a typed not-found error if the
  item is missing, already deleted, or belongs to another household.
- `update_item(db, *, household, user, pantry_item_id, quantity, unit, expires_at)
  -> PantryItem` — updates supplied fields, emits `food.pantry_item.updated`. Same
  not-found behaviour.

The existing photo-capture endpoint is **not** changed; it may adopt `add_item` later.

### `app/services/llm.py` *(extend)*
- `CHAT_SYSTEM` — versioned system prompt (`# v0.1 — initial chat prompt`): Hearth persona
  (warm, frugal, concise — consistent with `BRIEFING_SYSTEM`), the action catalog and its
  JSON schema, the §3 rules, the preservation safety block (from `PRESERVATION_SYSTEM`),
  and "Respond ONLY with valid JSON conforming to the schema; no preamble, no code fences."
- `chat_turn(history: list[dict], context: str, page: str) -> ChatTurnResult` — model
  `MODEL_FAST` (Sonnet); prepends `CHAT_SYSTEM` + the page-context block as `system`;
  passes the message history (capped to the last ~20 messages for cost); parses the
  response with `_extract_json` and validates into `ChatTurnResult`.

### `apps/web/src/components/ChatSidebar.tsx` *(rewrite `send` + add routing)*
- Becomes route-aware via `usePathname()`.
- On open, and whenever the path changes while open: `POST /ai/conversations { page }`,
  store `conversation_id`, render the returned `messages`.
- `send()`: `POST /ai/conversations/{id}/messages { content }`; show a "thinking…" state;
  disable the input while in flight; append the `reply`; render each `ActionResult` as a
  small chip beneath the assistant message (✓ green for `ok`, ⚠ amber for `error`, using
  the `summary` text).
- Footer line: drop "live chat", keep the voice mention as future scope.

### `apps/web/src/lib/api.ts` *(extend)* and `src/lib/types.ts`
Add typed client functions `openConversation(page)` and `sendChatMessage(id, content)`,
plus the matching TS types (`ChatMessage`, `ActionResult`, `ChatTurnResponse`,
`ConversationOpenResponse`).

## 8. Error handling

- **Malformed LLM JSON:** caught at the `services/chat.py` boundary — LLM output is
  untrusted input. Returns a graceful fallback assistant message ("I had trouble with
  that — could you rephrase?") rather than a 500. The fallback is still persisted.
- **Per-action failure** (bad/missing ID, wrong-household entity): that action's
  `ActionResult` gets `status="error"` with a human-readable `error`; the turn still
  succeeds (HTTP 200) and sibling actions still execute.
- **Conversation not found / wrong household:** 404.
- **Empty `page` string:** 400. Unknown-but-nonempty routes fall back to `general`.
- Internal errors otherwise propagate to FastAPI's 500 handler (per CLAUDE.md).

## 9. Testing

LLM is mocked following the existing patterns in `apps/backend/tests/` (mock at the
`llm.chat_turn` level rather than the CLI subprocess). Coverage:
- Action-protocol parsing: well-formed and malformed LLM output → `ChatTurnResult` /
  graceful fallback.
- `_execute_action` for each of the six action types — success and the failure path
  (bad ID, missing entity).
- `get_or_create_conversation` — idempotent per `(household, page)`; distinct pages yield
  distinct conversations.
- `build_page_context` — known pages and the `general` fallback.
- Endpoint smoke test: `POST /conversations` then `POST .../messages` with a mocked
  `chat_turn` returning a known `add_pantry_item` → assert the pantry item is created, the
  `food.pantry_item.added` event row exists, and both messages are persisted.

## 10. Known tradeoffs

1. **`generate_meal_plan` from chat is a synchronous Opus call.** A chat turn that triggers
   it can spin for 1–3 minutes. Acceptable pre-launch with a clear "thinking…" UI state.
   Making it async would need a job queue — out of scope and requires human sign-off per
   CLAUDE.md ("Don't introduce a new database, queue, or cache without checking first").
2. **Claude's `reply` states intent, not confirmed outcome** (single-call protocol). The
   per-action result chips provide the confirmed ground truth.

## 11. Out of scope for v1

Voice; conversation-list / multi-thread UI; streaming responses; async meal-plan
generation; bills/community-tier actions; changing the photo-capture endpoint.
