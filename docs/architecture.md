# Architecture

This doc captures the load-bearing design decisions. If you're adding a feature
and aren't sure whether a new table should go in `core`, in a tier schema, or in
one of the cross-cutting schemas, read this first.

## Tiers

Three tiers, shipping in order:

- **Tier A — Food.** Pantry, recipes, meal planning, preservation, waste, shopping.
- **Tier S — Bills & health.** Medical bills, tax, insurance, utilities. Future.
- **Tier B — Community.** Sharing, repair, swaps. Future.

Each tier lives in its own Postgres schema (`food`, eventually `bills`, `health`,
`community`). Tier-specific tables only reference `core` tables; tiers never
reference each other directly.

## Cross-cutting modules

These ship alongside Tier A and serve every tier:

- **`content`** — curated YouTube/RSS/Reddit ingestion + AI-generated articles.
  A `ContentItem` has a `topic` field that routes it to the right tier.
- **`ai`** — Claude conversations (chat sidebar), voice sessions, daily briefings.
  A `Conversation` has a `scope` field (general / food / bills / community).
- **`tracking`** — money saved, waste avoided, streaks, badges. Aggregates events
  emitted by any tier. The "saved $X this month" headline lives here.

These are cross-cutting because they don't *do* anything specific to food vs.
bills — they're surfaces (content feed, chat, dashboard) that compose tier data.

## Schema map

```
core/
  users
  households
  household_members      (multi-user with owner | member | viewer roles)
  subscriptions          (tier_a_enabled, tier_s_enabled, tier_b_enabled)
  feature_flags
  events                 (polymorphic activity log)
  audit_log

food/                    Tier A
  ingredients
  pantry_locations
  pantry_items
  receipts               (receipt-scan capture path)
  recipes
  recipe_ingredients
  recipe_steps
  meal_plans
  planned_meals
  shopping_lists
  shopping_items
  preservation_jobs
  food_waste_events

content/                 Cross-cutting
  sources                (YouTube channels, RSS feeds, subreddits)
  items                  (videos, posts, threads, AI articles)
  ingestion_jobs         (one row per poll/run)
  bookmarks

ai/                      Cross-cutting
  conversations
  messages
  voice_sessions
  briefings              (daily proactive summary)

tracking/                Cross-cutting
  budgets
  spend_entries
  savings_events
  streaks
  badge_definitions
  badge_awards
```

## Design rules

1. **Core entities are tier-agnostic.** `users`, `households`, etc. never know
   about food or bills. Use `core.events` (polymorphic) to log activity.
2. **Each tier owns its own schema.** New tier = new schema. Don't add
   tier-specific columns to `core` tables.
3. **JSONB `metadata_` on every domain table.** Extend without migrations until
   a field is hot enough to deserve a real column + index.
4. **Soft delete via `deleted_at`.** Hard delete only when GDPR/CCPA forces it.
5. **Audit through `core.audit_log`.** WHO did WHAT.
6. **Activity through `core.events`.** Polymorphic: `entity_type + entity_id`.
   Used by streaks, undo, analytics. New tiers emit new event types without
   touching core. Known food-tier event types: `food.receipt.parsed`,
   `food.pantry_item.added`, `food.pantry_item.removed` (chat-driven removal),
   `food.pantry_item.updated` (chat-driven update), `food.pantry_item.wasted`,
   `food.meal.cooked`; and content-tier `content.item.enriched` (emitted when a
   saved video is enriched with AI-extracted ingredients).

## How tiers compose with cross-cutting modules

Example: receipt scan flow (Tier A pantry capture path).

1. `POST /api/v1/food/pantry/receipt` with photo bytes.
2. `services.llm.extract_receipt(image)` returns structured items.
3. We insert: `food.receipts` row, N `food.pantry_items` rows, and a
   `tracking.spend_entries` row for the total. All in one transaction.
4. We emit a `core.events` row: `food.receipt.parsed` with item count + total.
5. The streak engine reads that event and may bump
   `tracking.streaks.kind = 'cooked_from_pantry'` (no — that's a different
   trigger; this would bump a `groceries_logged` streak if defined).
6. If the receipt total is under the weekly budget, log a
   `tracking.savings_events` row with `kind = 'under_budget'`.

The food module didn't have to know about tracking; it just emitted an event.
Tracking is a subscriber.

## Adding a new tier (Tier S checklist)

1. Migration: `CREATE SCHEMA IF NOT EXISTS bills`.
2. Models: `app/models/bills.py`. Same shape as `food.py`. FK to `core.households(id)`
   and `core.users(id)`.
3. Register in `app/models/__init__.py`.
4. Router: `app/routers/bills.py`. Mount under `/api/v1/bills`.
5. Set `tier_s_enabled = true` on user subscriptions to gate UI.
6. Run `alembic revision --autogenerate -m "tier_s_bills_models"`.
7. Add a few `content.sources` rows with `topic = 'bills'` (e.g. bill negotiation
   subreddits, blogs). Same ingestion pipeline works.
8. AI conversations with `scope = 'bills'` automatically get bill context in
   their system prompt — that's a service-layer concern, not a schema concern.

Zero changes to `core`, `food`, or any of the cross-cutting schemas required.

## AI surface design

Four surfaces, all reading from the same `ai.conversations` table:

- **Chat sidebar** (`surface = 'sidebar'`) — persistent panel on every page.
- **Inline actions** (`surface = 'inline'`) — "Stretch my pantry" creates a
  one-shot conversation that closes after the response.
- **Voice** (`surface = 'voice'`) — "hey Hearth" sessions persist to
  `ai.voice_sessions` and reference a parent `conversation`.
- **Daily briefing** (`surface = 'briefing'`) — scheduled job at 7am local time
  generates a `Briefing` row, optionally sends push/email.

Model selection (`ai.conversations.model`) defaults to Sonnet 4.6; switch to
Opus 4.7 for hard reasoning (multi-constraint meal plan optimization, bill
negotiation strategy). Haiku 4.5 for cheap classification (content ranking,
ingredient canonicalization).

## Tracking design

Two flavors of state:

- **Append-only events** — `savings_events`, `spend_entries`, `food_waste_events`.
  Easy to recompute aggregates, never lose history.
- **Materialized rollups** — `streaks`. Updated by event-processing logic.
  Optimization for the dashboard.

The dashboard query is roughly:

```sql
SELECT
  (SELECT SUM(amount_usd) FROM tracking.savings_events
     WHERE household_id = $1 AND occurred_on >= date_trunc('month', now())) as saved_this_month,
  (SELECT SUM(estimated_value_usd) FROM food.food_waste_events
     WHERE household_id = $1 AND occurred_on >= date_trunc('month', now())) as wasted_this_month,
  ...
```

Streaks update on event ingest, not at dashboard read time.

## Non-goals for v1

- No auth UI. Dev-mode header injects a fixed user_id.
- No payments.
- No mobile app (folder reserved; not populated).
- No offline mode. Always-online v1.
- No background queue. Ingestion jobs run synchronously triggered by API call.
  Add Celery/RQ/Cloud Tasks when volume justifies it.
