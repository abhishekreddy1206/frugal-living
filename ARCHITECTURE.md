# ARCHITECTURE.md — frugal-living

> Deep dive on the data model and the reasoning behind it. CLAUDE.md is the entry point; this is for when you're modifying schemas, adding a new tier, or debugging schema decisions.

---

## Table of contents

1. [Mental model](#1-mental-model)
2. [The schema namespace per tier](#2-the-schema-namespace-per-tier)
3. [Core tables, in detail](#3-core-tables-in-detail)
4. [The Tier A schema (`food`)](#4-the-tier-a-schema-food)
5. [The `core.events` table — the polymorphic activity log](#5-the-coreevents-table--the-polymorphic-activity-log)
6. [JSONB `metadata` everywhere — when and how](#6-jsonb-metadata-everywhere--when-and-how)
7. [Soft delete and audit log](#7-soft-delete-and-audit-log)
8. [Adding a new tier — step-by-step playbook](#8-adding-a-new-tier--step-by-step-playbook)
9. [Index strategy](#9-index-strategy)
10. [Migration patterns](#10-migration-patterns)
11. [What we deferred and why](#11-what-we-deferred-and-why)

---

## 1. Mental model

The single most important thing to internalize: this isn't one product, it's a *suite*. The suite ships in tiers (A then S then B), and the data model needs to absorb each tier without breaking changes to anything that came before.

The architecture has three layers:

```
┌─────────────────────────────────────────────────────┐
│                   CORE (shared)                     │
│  Identity, household, billing, events, audit, flags │
│  Tier-agnostic. Stable. Rarely changes.             │
└─────────────────────────────────────────────────────┘
                          ▲
                          │  (foreign keys point IN to core, never out)
                          │
   ┌──────────────────────┼──────────────────────────┐
   │                      │                          │
┌──▼────────┐      ┌─────▼─────┐           ┌────────▼──────┐
│  food     │      │  bills    │           │  community     │
│  (Tier A) │      │  (Tier S) │           │  (Tier B)      │
│  Now      │      │  Future   │           │  Future        │
└───────────┘      └───────────┘           └────────────────┘
```

Rules that fall out:

- Tier schemas FK into `core.*` only. Never tier-to-tier (e.g. `food` never references `bills`). If you find yourself wanting to FK between tiers, route through `core` (usually `core.events`).
- Core never knows about tiers. No `pantry_count` on `core.households`. If core needs an aggregate, it reads `core.events`.
- A new tier is a new Postgres schema plus a new model module plus new routers. Nothing in core changes.

---

## 2. The schema namespace per tier

Postgres schemas (not databases) are the unit of tier isolation. Why schemas:

- Single connection pool, single migration history, single backup — operationally simple.
- Permissions can be granted per-schema later (e.g. for an analytics read-replica role that only sees `core` and aggregated tier views).
- Clear table names: `food.pantry_items` reads better than `pantry_items` with a `tier` column or `food_pantry_items` with a prefix.
- ORM-friendly: SQLAlchemy supports schemas via `__table_args__ = {"schema": "food"}`.

Why not one schema with prefixed table names: harder to grant tier-scoped permissions; less discoverable; encourages prefix drift.

Why not one database per tier: way too much operational complexity for our scale; cross-tier joins (which we'll want for analytics) become painful; backup/restore overhead.

**The schemas:**

| Schema | Purpose | Status |
|---|---|---|
| `core` | Identity, household, billing, events, audit, flags | Live |
| `food` | Tier A: pantry, recipes, meals, preservation, shopping | Live |
| `bills` | Tier S: subscriptions, bill negotiation, utilities | Future |
| `health` | Tier S: medical bills, insurance, providers | Future (separated from `bills` for PHI isolation) |
| `community` | Tier B: sharing, swaps, skill barter | Future |

The schemas are created in migration `0001_init_schemas.py`. Adding a new schema is a one-line migration.

---

## 3. Core tables, in detail

`core.users` — Identity. Email + password hash + display name. `is_active` toggle. JSONB `metadata` for prefs that aren't yet first-class.

`core.households` — The unit of billing and data ownership. One household has many users (via `household_members`), one currency, one timezone, one locale. Dietary restrictions, equipment lists, household-wide preferences go in `metadata`.

`core.household_members` — Join table between users and households. `role` column: `owner | member`. (Future: `guest`, `child`, `admin`.)

`core.subscriptions` — One row per user. Plan + status + three tier-enabled booleans. **Why per-user, not per-household:** simpler billing in the US (Apple/Google IAP, Stripe), and the household concept exists for content sharing not payment sharing. Members of a household see what the *owning user's* subscription allows.

`core.feature_flags` — Server-side feature flags. `key` (string), `enabled_globally` (bool), `rollout_percent` (0..100). Used for dark launches of new tier features. Check a flag with a tiny helper in `app/services/flags.py` (not yet written).

`core.events` — The polymorphic activity log. See section 5. Likely to become our largest table; designed accordingly.

`core.audit_log` — Who did what. Separate from `events` because it tracks *actors* (including system/admin actions), not just user-facing happenings. Important for trust, debugging, and future GDPR/CCPA requests.

---

## 4. The Tier A schema (`food`)

### The pantry trinity (priority 1)

`food.ingredients` — Canonical ingredient catalog. Every "tomato" in every pantry, every recipe, every shopping list resolves to one canonical `food.ingredients` row when possible. The `aliases` array column makes lookups fuzzy ("tomatoes", "Roma tomato", "tomate" all resolve). This is the most important table for cross-feature consistency.

`food.pantry_locations` — Where things live. Pantry, fridge, freezer, root cellar, spice rack. Per-household. Temperature and metadata are extension points (a "garage freezer" might be flagged for power-outage risk in the future).

`food.pantry_items` — A unit of food in the household. Has a `raw_name` (as captured) and an optional `ingredient_id` (canonical resolution). Quantity, unit, location, dates (purchased, opened, expires), `source` (manual, photo_capture, receipt_scan, imported), `confidence` (0..1, for AI-captured items), `photo_url`, notes. Indexed on `(household_id, expires_at)` because the most common query is "show me what's expiring soon."

### The recipe trinity (priority 2)

`food.recipes` — Recipe metadata. Name, slug, description, source, servings, times, cuisine, difficulty, tags. `estimated_cost_usd` and `estimated_cost_per_serving_usd` enable budget-aware planning. `is_user_created`, `created_by_user_id`, `is_ai_generated` distinguish provenance.

`food.recipe_ingredients` — Join: recipe + ingredient (or just raw_name when no canonical match). `is_optional`, `substitutions` (array of strings — substitution suggestions baked in).

`food.recipe_steps` — Ordered steps with content + optional duration. Duration in seconds enables timer integration later.

### The planning layer (priority 3)

`food.meal_plans` — Weekly plan. Per-household, week_start date, target_budget, status (`draft | active | archived`).

`food.planned_meals` — Individual planned meals. Recipe + date + meal_type (breakfast | lunch | dinner | snack) + servings + status (`planned | prepped | cooked | skipped`).

### Shopping

`food.shopping_lists` — Lists. Tied to a meal plan or freestanding.
`food.shopping_items` — Items on a list. Optional ingredient_id, raw_name, quantity, unit, store, estimated/actual price.

### Preservation (Tier A expansion)

`food.preservation_jobs` — A canning batch, fermentation crock, dehydration cycle. `method` enum: `canning_water_bath | canning_pressure | freezing | dehydrating | fermenting | pickling | curing`. Has `safety_check_passed` boolean — the preservation coach must explicitly mark safety verified before storage. `expires_at` is computed and stored to enable rotation reminders.

### Food waste tracking

`food.food_waste_events` — Each waste incident: ingredient, quantity, reason, estimated value, date. Powers the user's "you saved $X this month" feedback loop and our key engagement metric.

---

## 5. The `core.events` table — the polymorphic activity log

This is the most important architectural decision in the codebase. Read this section carefully.

### What it is

A single table that captures every meaningful action across every tier:

```python
class Event:
    id: UUID
    household_id: UUID | None
    user_id: UUID | None
    event_type: str          # e.g. "food.pantry_item.added"
    entity_type: str | None  # e.g. "pantry_item"
    entity_id: UUID | None
    payload: dict            # JSONB, arbitrary
    created_at: datetime
```

### Why

1. **Streaks, badges, gamification.** "You cooked 5 meals this week" reads from events.
2. **Undo.** Every state change emitted as an event can be reversed by reading and replaying inversely.
3. **Analytics.** What features matter, where users drop off, all from one stream.
4. **The future community feed.** When Tier B ships, the household activity feed reads from events.
5. **Cross-tier insight.** "Users who track preservation jobs are 3x more likely to convert on bill negotiation" — only answerable with a unified event stream.
6. **New tier additions are zero-friction.** Tier S emits `bills.negotiation.completed` — no schema change in core.

### Event type naming

Strict convention: `<tier>.<entity>.<action>`. Always lowercase. Always singular entity. Actions are past-tense verbs.

Examples:
- `food.pantry_item.added`
- `food.pantry_item.expired`
- `food.meal.cooked`
- `food.meal.skipped`
- `food.preservation_job.started`
- `food.preservation_job.completed`
- `food.shopping_item.purchased`
- `bills.negotiation.completed` (future)
- `bills.subscription.cancelled` (future)
- `community.swap.matched` (future)

When you add a new event type, document it in section 5.5 of this file (alphabetical).

### Payload conventions

The `payload` JSONB column carries event-specific data. Keep it small. Include enough that a consumer reading just events (not joining to entity tables) can compute basic things. Example payload for `food.meal.cooked`:

```json
{
  "recipe_id": "...",
  "recipe_name": "Lentil dal",
  "servings": 4,
  "estimated_value_usd": 8.50,
  "cooked_from_pantry_pct": 0.85
}
```

Don't put PII in payloads beyond what's already in the entity row. Don't put PHI (medical) in events — health events emit minimal references and detail lives in `health.*` tables with stricter access controls.

### Indexing

The two queries that matter:
1. "Show me a household's recent activity" → `(household_id, created_at DESC)` — already indexed.
2. "Show me everything that happened to a specific entity" → `(entity_type, entity_id)` — already indexed.

Add specialized indexes (e.g. `(event_type, created_at)` for analytics queries) only when the query plan demands it.

### Partitioning (future)

When `core.events` exceeds ~100M rows or becomes a write hot spot, partition by `created_at` monthly. Postgres native partitioning. Migration written when needed.

### 5.5 Event type catalog (alphabetical)

Maintained list of every event type defined in the system. Update as you add new ones.

**Tier A — food**
- `food.meal.cooked`
- `food.meal.skipped`
- `food.meal_plan.created`
- `food.pantry_item.added`
- `food.pantry_item.consumed`
- `food.pantry_item.expired`
- `food.pantry_item.wasted`
- `food.preservation_job.completed`
- `food.preservation_job.started`
- `food.recipe.generated`
- `food.shopping_item.purchased`

(Future tiers' types added here as introduced.)

---

## 6. JSONB `metadata` everywhere — when and how

Every domain table has a column named `metadata` (Python attribute `metadata_` because `metadata` is reserved by SQLAlchemy). It's a JSONB column with a default of `{}`.

### When to use it

- A field is *transient* — useful for a few weeks while you figure out if it matters.
- A field is *sparse* — only relevant for some rows.
- A field is *experimental* — you don't want a migration yet.
- A field is *third-party-sourced* and might have variable shape (e.g. an Instacart product response).

### When NOT to use it

- The field is core to queries (will be in `WHERE` or `ORDER BY` often) — make it a real column.
- The field has strict typing or constraints — make it a real column or add a `CHECK`.
- You're using JSONB to avoid thinking — make it a real column.

### How to index JSONB paths

When a JSONB path becomes hot:

```sql
CREATE INDEX idx_pantry_items_metadata_brand
ON food.pantry_items USING GIN ((metadata->'brand'));
```

Or for whole-document containment:

```sql
CREATE INDEX idx_pantry_items_metadata_gin
ON food.pantry_items USING GIN (metadata);
```

The whole-document GIN index supports `metadata @> '{"brand": "Costco"}'` queries but is larger; prefer path-specific indexes once you know the access pattern.

### Promotion path

When a JSONB field is used in queries often enough to justify a real column:

1. Add the new column in a migration (nullable initially).
2. Backfill from JSONB in the same migration: `UPDATE food.pantry_items SET brand = metadata->>'brand' WHERE metadata ? 'brand';`
3. Update application code to write both for one release.
4. In a follow-up migration, drop the JSONB key.

---

## 7. Soft delete and audit log

### Soft delete

Every domain table inherits `TimestampMixin` which includes `deleted_at: datetime | None`. Rules:

- Never `DELETE` from these tables. Set `deleted_at = NOW()`.
- Every query filters `WHERE deleted_at IS NULL` (or uses a global SQLAlchemy filter — see future `app/db.py` enhancement).
- Hard deletes happen only via a dedicated admin path that audits the deletion.
- Cascading soft-deletes are application-level (when you soft-delete a meal plan, soft-delete its planned meals).

### Audit log (`core.audit_log`)

Distinct from `core.events`:
- Events = things that happened in the product (user-facing).
- Audit = who did what (actor-facing).

Audit log captures:
- Admin actions (data corrections, hard deletes, support tickets).
- Permission changes.
- System-level mutations (e.g. a backfill that touches many rows).
- Anything we'd need to defend in a GDPR/CCPA request.

When in doubt, write to both. They serve different consumers.

---

## 8. Adding a new tier — step-by-step playbook

Concrete example: shipping the **bill negotiation** feature in Tier S.

### Step 1 — Create the schema

```python
# alembic/versions/00XX_add_bills_schema.py
def upgrade():
    op.execute("CREATE SCHEMA IF NOT EXISTS bills")
```

### Step 2 — Add the model module

Create `apps/backend/app/models/bills.py`. Mirror `food.py` patterns:

- Every table has `__table_args__ = {"schema": "bills"}` (or a tuple with indexes + the schema dict).
- Every domain table inherits `TimestampMixin`.
- Every domain table has `metadata_: Mapped[dict]`.
- Foreign keys to core: `ForeignKey("core.households.id")`, `ForeignKey("core.users.id")`.
- **No foreign keys to `food.*`.** If you need a connection, route through `core.events`.

### Step 3 — Register the module

In `apps/backend/app/models/__init__.py`:

```python
from app.models import core      # noqa: F401
from app.models import food      # noqa: F401
from app.models import bills     # noqa: F401  ← add this
```

### Step 4 — Generate the migration

```bash
uv run alembic revision --autogenerate -m "add_bills_tier"
# inspect the generated file, edit if needed
uv run alembic upgrade head
```

### Step 5 — Add routers

Create `apps/backend/app/routers/bills.py`. Mount in `apps/backend/app/main.py`:

```python
app.include_router(bills.router, prefix="/api/v1/bills", tags=["bills"])
```

### Step 6 — Gate behind the tier flag

In any router or service handling bills:

```python
if not subscription.tier_s_enabled:
    raise HTTPException(403, "Tier S not enabled")
```

Optionally combine with a `core.feature_flags` check for staged rollout.

### Step 7 — Wire events

When a negotiation completes, emit:

```python
emit_event(
    db,
    household_id=household.id,
    user_id=user.id,
    event_type="bills.negotiation.completed",
    entity_type="negotiation",
    entity_id=neg.id,
    payload={"savings_usd": float(neg.savings), "provider": neg.provider},
)
```

(`emit_event` is a helper to be added in `app/services/events.py` — write it the first time you need it.)

### Step 8 — LLM functions

Add new functions to `app/services/llm.py` (or split into `app/services/llm/bills.py` if it grows). All Anthropic calls continue to go through this layer.

### Step 9 — Frontend

Add the route and components under `apps/web/src/app/bills/`. Use the same Tailwind aesthetic. API calls via the `api()` helper.

### Step 10 — Update CLAUDE.md

Add the new tier to the schema list and current state. Add new event types to the catalog in this file.

That's it. No `core` changes. No `food` changes. No breaking migrations.

---

## 9. Index strategy

Default indexes (already in models):

- Primary keys (UUID, B-tree).
- Foreign keys to `core.households(id)` — most queries scope by household.
- "Find by recency": `(household_id, created_at)` on events.
- Domain-specific: `(household_id, expires_at)` on pantry items (expiration is the hot query).

When to add an index:

1. The query plan shows a sequential scan on a non-trivial table size.
2. A specific column is in `WHERE` or `ORDER BY` for >5% of queries.

When not to add an index:

- The table is small (<10K rows). Postgres scans are fast.
- The column is mutable and high-cardinality (writes will be expensive).
- You're guessing. Measure first.

### JSONB indexes

See section 6. Prefer path-specific GIN indexes over whole-document indexes once access patterns are known.

### Full-text search

Recipe search will eventually need full-text search. Plan: `tsvector` column + GIN index, computed via `tsvector_update_trigger`. Defer until search relevance complaints appear.

---

## 10. Migration patterns

### Always test migrations on a copy first

```bash
# Dump local DB
pg_dump frugal_living > /tmp/dump.sql
# Test upgrade
uv run alembic upgrade head
# If broken: restore
psql -c "DROP DATABASE frugal_living; CREATE DATABASE frugal_living;"
psql frugal_living < /tmp/dump.sql
```

### Make migrations reversible

Always write a `downgrade()`. Even if you never run it, the discipline catches errors.

### Don't autogenerate destructive changes blindly

Alembic's `autogenerate` doesn't know intent. If it suggests `op.drop_column()`, verify you really want that. For column renames, autogenerate produces drop+add — fix it manually to `op.alter_column(... new_column_name="...")`.

### Backfills in migrations

For columns added with a NOT NULL default, do this in three steps:

1. Migration A: add column nullable.
2. Backfill data (in migration or application code).
3. Migration B: alter to NOT NULL.

Don't combine all three in one migration if the backfill is non-trivial — long-running migrations block deploys.

### Cross-schema migrations

Always use fully qualified names: `op.execute("UPDATE food.pantry_items SET ...")`. Postgres search_path can lie to you.

---

## 11. What we deferred and why

These decisions were made deliberately. Document them so future-Claude doesn't relitigate.

| Deferred | Why | Trigger to reconsider |
|---|---|---|
| Async SQLAlchemy | Sync is simpler; latency is fine for v1 | First time a request blocks for >500ms on DB |
| Redis caching | No real load yet | When Anthropic costs exceed $500/mo and prompt caching helps |
| Background job queue (Celery/RQ) | No long-running tasks yet | When pantry photo processing needs to run async |
| File storage (S3/R2) | Photos pass as base64 for v1 | When we want to keep photos beyond a request |
| Real auth | Stub user is fine pre-launch | First non-Abhishek user |
| Mobile app | Web first; Expo wraps later | When mobile conversion data justifies it |
| GraphQL | REST is fine for our shape | Never, probably |
| Microservices | Monolith is fine forever at our scale | Never, probably |
| Event sourcing (vs current event log) | Current pattern serves the need without full ES overhead | If we need point-in-time reconstruction of arbitrary state |
| Multi-tenancy isolation beyond `household_id` | Single-tenant Postgres is fine | If we hit a regulated industry use case |
| Sharding | Vertical scaling will go far | When a single Postgres can't hold us — way later |

When you reconsider one of these, update the row with the new decision.

---

End of architecture doc. When in doubt about a schema change, ask: "does this respect the 7 inviolable rules in CLAUDE.md?" If yes, ship it. If no, redesign.
