# Phase 1 — Household Inventory: Design Spec

**Date:** 2026-05-21
**Status:** Approved design. Next step: implementation plan via `writing-plans`.
**Parent:** `2026-05-21-tier-b-community-marketplace-design.md` (Tier B roadmap, Phase 1 of 4).

---

## 1. Goal

A single-household catalog of durable possessions (games, tools, books, gear) — the things a household owns beyond the food pantry. Captured by photo or entered manually, browsable at a new `/inventory` page, and queryable + editable through the AI chat assistant.

Phase 1 is **single-household only** — zero marketplace, zero multi-household behavior. It is independently valuable ("know what you own, stop re-buying") and is the lowest-risk slice of the Tier B roadmap. This is also the migration that **creates the `community` schema**, following the `ARCHITECTURE.md` "Adding a new tier" checklist.

## 2. Decisions locked

| Decision | Choice | Rationale |
|---|---|---|
| **Item identity** | Per-unit rows | You lend/track a *specific* item, not "one of N". An optional `quantity` field still covers genuinely fungible bulk ("8 folding chairs"). |
| **Taxonomy** | Fixed category enum + free-form tags | The enum gives clean browse/filter and marketplace-ready categories; tags add finer search and cost nothing. |
| **Chat** | Full parity in Phase 1 | Inventory is wired into the AI chat with read Q&A *and* add/update/remove actions, matching the food chat's CRUD action set. |
| **Search mechanism** | Context-grounding, **not RAG** | One household's inventory is tens–low-hundreds of items — it fits in the context window. Vector search (`pgvector`) would be a new extension needing sign-off; not warranted until marketplace-wide search in Phase 2+. |

## 3. Data model — `community.items`

New `community` schema. The table follows all 7 inviolable rules: `community` schema, `metadata_` JSONB, `deleted_at` soft delete, FK only into `core`.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `household_id` | UUID FK `core.households` | not null, indexed |
| `created_by_user_id` | UUID FK `core.users` | nullable — audit; mirrors `food.recipes` |
| `name` | String(200) | "DeWalt 20V Drill", "Catan" |
| `category` | String(32) | enum: `tools` / `games` / `books` / `kitchen` / `outdoor` / `electronics` / `furniture` / `kids` / `sports` / `other` |
| `tags` | `ARRAY(String)` | free-form, AI-suggested; default `[]` |
| `quantity` | Integer, default 1 | covers fungible bulk |
| `condition` | String(16), nullable | enum: `new` / `like_new` / `good` / `fair` / `poor` |
| `estimated_value_usd` | Numeric(10,2), nullable | replacement value — powers Phase 3 `borrowed_not_bought` savings |
| `location` | String(120), nullable | free-text storage location ("garage"). A dedicated `item_locations` table is **deferred** — a string suffices for Phase 1 |
| `acquired_on` | Date, nullable | |
| `photo_url` | String(500), nullable | |
| `source` | String(32), default `manual` | `manual` / `photo_capture` — mirrors `PantryItem.source` |
| `confidence` | Numeric(3,2), nullable | 0..1, for AI-captured items |
| `notes` | Text, nullable | |
| `metadata_` | JSONB, default `{}` | DB column name `metadata` |
| `created_at` / `updated_at` / `deleted_at` | via `TimestampMixin` | |

Index: `idx_items_household_category` on `(household_id, category)`.

The model lives in a new `app/models/community.py`, registered in `app/models/__init__.py`.

## 4. LLM — `extract_items_from_image`

New function in `app/services/llm.py`, using `MODEL_VISION` (Sonnet 4.6). Reuses the exact vision transport as `extract_pantry_from_image` — the image is written to a temp file and opened via the CLI Read tool.

- **Input:** base64 image + media type (a photo of a game shelf, a tool pegboard, a bookcase).
- **Output:** structured JSON — a list of `{raw_name, category, tags, quantity, condition, estimated_value_usd, confidence, notes}`. `category` is constrained to the enum in the prompt.
- Parsed defensively with Pydantic before returning to callers.
- Prompt defined at module level, versioned `# v0.1 — initial item extraction prompt`.

## 5. API — new router `app/routers/community.py`

Mounted at `/api/v1/community` in `app/main.py`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/community/items` | List the household's items; optional `category` query filter; `deleted_at IS NULL`. |
| `POST` | `/community/items` | Manually create one item. |
| `POST` | `/community/items/capture` | Photo → many items (mirrors `/food/pantry/capture`): extract, persist, emit events. |
| `PATCH` | `/community/items/{id}` | Update item fields. |
| `DELETE` | `/community/items/{id}` | Soft delete (set `deleted_at`). |

Every route applies a plain `household_id == household.id` ownership filter — **no visibility helper yet**; that arrives in Phase 2 when multi-household reads appear. Phase 1 is scoped exactly like Tier A. Routers stay thin; logic lives in the service layer.

## 6. Events

Emitted via `emit_event`, `entity_type="item"`, following the `<tier>.<entity>.<action>` convention:

- `community.item.added` — on create (manual) and once per captured item.
- `community.item.updated` — on PATCH.
- `community.item.removed` — on soft delete.

## 7. Supporting pieces

- **Schemas:** new `app/schemas/community.py` — `ItemRead`, `ItemCreate`, `ItemUpdate`, `ExtractedItem`, `ItemCaptureRequest`, `ItemCaptureResponse`.
- **Service layer:** new `app/services/community/` **package** (`__init__.py` + `items.py`). Tier B will accumulate several service modules (items, listings, exchanges, visibility); a package keeps them grouped rather than sprawling flat.
- **Migration:** one Alembic migration — `CREATE SCHEMA IF NOT EXISTS community` + the `community.items` table. Autogenerated after the model is added, then reviewed.
- **Subscription gating:** flip `tier_b_enabled=True` on the dev subscription seed in `app/auth.py` so the feature is reachable in dev.
- **Frontend:** a new `/inventory` page mirroring `/pantry` — a photo-capture → review → confirm flow, a manual add form, a category filter, and the warm editorial aesthetic. Uses the `api()` helper in `src/lib/api.ts`.

## 8. Chat parity

Wires the inventory into the existing per-page chat assistant (`app/services/chat.py`), mirroring the food chat. All changes are **additive** — no food chat behavior is altered.

- **New page:** `/inventory` → page key `inventory` in `_ROUTE_TO_PAGE`. `get_or_create_conversation` becomes scope-aware (it hardcodes `scope="food"` today) and creates the inventory conversation with `scope="community"`.
- **Grounding context:** a new `_inventory_context(db, household)` lists `community.items` with their `id`s (so update/remove actions can reference them), mirroring `_pantry_context`. `build_page_context` includes it on the `inventory` page. Q&A — "where's my drill?", "do I own a tent?", "what board game seats 6?" — works on the inventory page. Cross-page inventory search is deliberately out of Phase 1, to keep other pages' prompts lean.
- **Actions:** three new action types — `add_inventory_item`, `update_inventory_item`, `remove_inventory_item` — with handlers added to the `_DISPATCH` dict, calling `app/services/community/items.py`. Each emits the same `community.item.*` events as the REST routes, so chat-driven and UI-driven changes are indistinguishable downstream.
- **`ChatAction` schema:** gains `inventory_item_id`, `category`, `tags`, `condition`, `estimated_value_usd`, `location` (reusing the existing `raw_name` / `quantity` fields), following the established flat-schema convention (`pantry_item_id`, `recipe_id`).
- **LLM prompt:** `llm.chat_turn`'s system prompt is extended to offer the inventory actions on the `inventory` page; prompt version bumped.

**Note on `chat.py` growth:** it becomes a multi-tier orchestrator — correct, since chat is cross-cutting per `ARCHITECTURE.md`, and its dispatch-dict + context-section structure absorbs this cleanly. If it keeps growing as more tiers wire in, splitting handlers into per-tier modules is a sensible later call — not needed at Phase 1.

## 9. Files touched

**New:** `app/models/community.py`, `app/routers/community.py`, `app/schemas/community.py`, `app/services/community/__init__.py`, `app/services/community/items.py`, an Alembic migration, the `/inventory` frontend page, and tests.

**Modified (all additive):** `app/models/__init__.py` (register model), `app/main.py` (mount router), `app/auth.py` (`tier_b_enabled` seed), `app/services/llm.py` (`extract_items_from_image` + `chat_turn` prompt), `app/services/chat.py` (scope-aware conversation, `_inventory_context`, dispatch entries, handlers), `app/schemas/ai.py` (`ChatAction` fields).

## 10. Tests

- Migration roundtrip — `community` schema + `community.items` create/drop.
- Endpoint smoke tests — create, list (+ category filter), capture (with the LLM mocked), patch, delete.
- Event-emission assertions for `community.item.{added,updated,removed}`.
- Chat tests — an inventory-page turn produces an `add_inventory_item` action that persists an item and emits the event; an inventory Q&A turn grounds its reply in `_inventory_context`.

## 11. Explicitly NOT in Phase 1

No listings, communities, sharing, geography, reputation, messaging, or any multi-household behavior. No `item_locations` table. No barcode/receipt capture for items. No cross-page inventory chat. Pure single-household catalog with chat parity.
