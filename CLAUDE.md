# CLAUDE.md — frugal-living

> Hi Claude. This is your memory for this project. Read it before doing anything. The deeper data-model rationale lives in `ARCHITECTURE.md` (repo root) — read that when you're modifying schemas or adding new tiers. Setup spec lives in `frugal_living_setup_instructions.md`.

---

## 🎯 30-second summary

**frugal-living** (working name: Hearth) is an AI-native consumer suite that helps US households live well on less. Macro thesis: AI is compressing white-collar wages, so households are shifting toward thrift, preservation, sharing, and DIY. The frugal-living category has a massive audience but 2014-vintage tooling. We're building the modern AI-native brand for it.

We are pre-launch. No real users yet. **Speed and clean foundations > polish.** Build the bones right so the suite expansion is frictionless later.

---

## 🚦 Current state

**Tier A MVP is built and runs.** All eight planned sprints are merged; the backend boots against Postgres, all migrations apply, and the test suite passes (134 tests). Frontend typechecks clean.

What's fully implemented:
- **`food` (Tier A)** — pantry photo capture, recipe stretcher, weekly meal plan, shopping list from plan, waste tracking + savings rollup, preservation coach (with botulism safeguards). All wired to Claude through `services/llm.py`.
- **`ai`** — daily briefings (Sprint 7); conversational chat assistant — per-page conversation threads with food-tier actions (add/remove/update pantry, log waste, mark cooked, generate meal plan) and grounded Q&A. Voice is still a stub.
- **`tracking`** — streaks + badges (Sprint 8). Dashboard / savings / budgets are still stubs.
- **`content`** — YouTube link capture + feed; captured videos are enriched (YouTube Data API description + AI ingredient extraction → canonical ingredient IDs) and the `/watch` library ranks them by pantry fit via `GET /content/recipe-suggestions`; `POST /content/enrich` backfills older videos. Channel/RSS/Reddit polling still stubbed.
- **Frontend** — a warm editorial design system (Fraunces + Hanken Grotesk, app shell with sidebar nav). Pages for all six food features (`/pantry`, `/stretch`, `/plan`, `/shopping`, `/preservation`, `/waste`), the `/watch` library, and a home dashboard.
- **Infra** — dev user/household, starter ingredients, and badge definitions are seeded on startup (`app/auth.py`). Two migrations applied (`0001` schemas, `0002` all tables). `./frugal up` runs the whole stack.

What's still stubbed (endpoints return placeholder JSON with a `todo` key):
- `food`: `/pantry/receipt`, `/pantry/barcode` (Sprint 1.5).
- `ai`: `/voice/*`; `GET /conversations` (thread-list view) is still a stub.
- `tracking`: `/dashboard`, `/savings`, `/budgets`.
- `content`: channel ingestion (`/sources`, `/ingest/run`); `services/{reddit,blog_importer}.py` are placeholders.
- `llm.extract_receipt` and `llm.rank_content_for_household` raise `NotImplementedError`.

**To run:** `./frugal up` (starts Postgres, applies migrations, launches backend + frontend). Needs Docker, `uv`, `pnpm`, and the `claude` CLI installed and logged in — the AI layer uses the Claude Code CLI, so no API key is required. `apps/backend/.env` only needs `DATABASE_URL`.

**Next implementation target:** Sprint 1.5 (receipt + barcode capture) or the `tracking` dashboard rollup.

---

## 🏗 The product, in one diagram

```
                    ┌─────────────────────┐
                    │  CORE (shared)      │
                    │  users, households, │
                    │  subscriptions,     │
                    │  events, audit_log  │
                    └─────────┬───────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
   ┌────▼─────┐         ┌────▼─────┐         ┌────▼─────┐
   │ Tier A   │         │ Tier S   │         │ Tier B   │
   │ FOOD     │         │ BILLS    │         │COMMUNITY │
   │ (now)    │         │ HEALTH   │         │ (later)  │
   │          │         │ (later)  │         │          │
   └──────────┘         └──────────┘         └──────────┘
```

Each tier = its own Postgres schema, its own router prefix (`/api/v1/food`, `/api/v1/bills`, …), its own model module. Core never references tier tables; tier tables FK only into core.

**Tier A scope (now):** pantry, recipes, meal planning, preservation, shopping lists, food waste.
**Tier S scope (later):** medical bill audit, bill negotiation, subscription killer, insurance, property tax.
**Tier B scope (later):** hyperlocal sharing, skill barter, mending, library aggregation.

---

## 🧭 Tier A — sprint ledger

| Sprint | Feature | Endpoint | LLM call | Status |
|---|---|---|---|---|
| 1 | **Pantry capture** | `POST /api/v1/food/pantry/capture` | `extract_pantry_from_image` (vision) | ✅ Done |
| 2 | **Recipe stretcher** | `GET /api/v1/food/recipes/stretch` | `stretch_recipes_for_pantry` | ✅ Done |
| 3 | **Weekly meal plan** | `POST /api/v1/food/meal-plans/generate` | `generate_weekly_plan` (Opus) | ✅ Done |
| 4 | **Shopping list** | `POST /api/v1/food/shopping-lists/from-plan` | — | ✅ Done |
| 5 | **Waste + savings** | `POST /api/v1/food/waste`, `GET /waste/savings` | — | ✅ Done |
| 6 | **Preservation coach** | `POST /api/v1/food/preservation/advice` | `preservation_advice` | ✅ Done |
| 7 | **Daily briefing** | `GET /api/v1/ai/briefings/today` | `generate_briefing` | ✅ Done |
| 8 | **Streaks + badges** | `GET /api/v1/tracking/streaks`, `/badges` | — | ✅ Done |
| 1.5 | Receipt + barcode capture | `POST /api/v1/food/pantry/{receipt,barcode}` | `extract_receipt` | ⛔ Stub |

The original MVP was sprints 1–3; sprints 4–8 followed. Receipt/barcode capture (1.5) and the cross-cutting `content` module remain.

---

## 🏛 The 7 inviolable rules

These encode design decisions that compound. Don't break them.

1. **Schema namespacing per tier.** Tier A → `food` schema. Tier S (future) → `bills`, `health`. Tier B (future) → `community`. New tiers add a schema. **Never** add tables to `public`. **Never** add tier-specific tables to `core`.

2. **Core tables stay tier-agnostic.** `core.users`, `core.households`, `core.subscriptions`, `core.events`, `core.feature_flags`, `core.audit_log` never reference tier-specific tables. Never add tier-specific columns here. If you're tempted to add a `pantry_count` to `core.households`, you're doing it wrong — it goes in `food`.

3. **Every domain table has a JSONB `metadata_` column** (Python attribute `metadata_`, DB column `metadata`). Lets us add fields per-row without migrations. Index a JSONB path with `CREATE INDEX … USING GIN ((metadata->'key'))` only when that path is hot.

4. **Soft delete by default.** Every domain table has `deleted_at`. Never `DELETE`. Filter `deleted_at IS NULL` in every query. If you need a hard delete, it goes through a dedicated admin path with audit logging.

5. **Emit events for everything meaningful.** Any mutation worth knowing about writes a row to `core.events` with a typed `event_type` like `food.pantry_item.added`, `bills.negotiation.completed`. Streaks, undo, analytics, the future community feed — all read from one table. Use the dotted-namespace convention: `<tier>.<entity>.<action>`.

6. **Single subscription, multi-tier flags.** One `core.subscriptions` row per user. Tier access via `tier_a_enabled`, `tier_s_enabled`, `tier_b_enabled` booleans. **Not** one subscription per product. We will regret it if we let this fragment.

7. **All LLM calls go through `app/services/llm.py`.** Never call Anthropic directly from a router or model. The service layer centralizes model selection, prompt versioning, retry logic, and (soon) prompt caching. Routers get parsed Python objects, not raw Claude responses.

---

## 🛠 Tech stack

- **Backend:** Python 3.11+ / FastAPI / SQLAlchemy 2.0 / Alembic / PostgreSQL 16
- **Frontend:** Next.js 14 (App Router) / TypeScript / Tailwind
- **AI:** Claude. `claude-sonnet-4-6` for fast paths and vision; `claude-opus-4-7` for hard reasoning (multi-constraint meal-plan optimization). **Currently routed through the Claude Code CLI (`claude -p`)** — no `ANTHROPIC_API_KEY` needed; the CLI authenticates with the local Claude Code subscription. This is temporary: switching back to the official Python SDK is a one-function change in `app/services/llm.py:get_client()` (the reference body is in its docstring). Everything else in `llm.py` is transport-agnostic.
- **Local DB:** Postgres via Docker Compose. **Do not switch to SQLite** — we use JSONB and Postgres array types pervasively.
- **Package managers:** `uv` (Python), `pnpm` (JS).
- **Auth:** Stubbed. Hardcoded dev user. Plug in Clerk or Auth.js before any real users.

---

## 📁 Project structure

```
frugal-living/
├── apps/
│   ├── backend/
│   │   ├── app/
│   │   │   ├── config.py            # pydantic-settings, reads .env
│   │   │   ├── db.py                # SQLAlchemy engine, session, Base
│   │   │   ├── main.py              # FastAPI app + router mounts
│   │   │   ├── auth.py              # dev-mode auth stub + fixture seeding
│   │   │   ├── models/
│   │   │   │   ├── __init__.py      # imports all model modules
│   │   │   │   ├── core.py          # users, households, subs, events, audit
│   │   │   │   ├── food.py          # Tier A: pantry, recipes, meals, ...
│   │   │   │   ├── ai.py            # conversations, voice, briefings
│   │   │   │   ├── content.py       # content sources, items, bookmarks
│   │   │   │   └── tracking.py      # budgets, savings, streaks, badges
│   │   │   ├── routers/
│   │   │   │   ├── health.py        # /healthz
│   │   │   │   ├── food.py          # /api/v1/food/*
│   │   │   │   ├── ai.py            # /api/v1/ai/*
│   │   │   │   ├── content.py       # /api/v1/content/*  (stubs)
│   │   │   │   └── tracking.py      # /api/v1/tracking/*
│   │   │   ├── schemas/             # Pydantic request/response models
│   │   │   │   ├── food.py
│   │   │   │   ├── content.py
│   │   │   │   └── tracking.py
│   │   │   └── services/
│   │   │       ├── llm.py           # ALL Claude calls (Claude Code CLI transport)
│   │   │       ├── events.py        # emit_event helper
│   │   │       ├── ingredients.py   # ingredient resolution + seeding
│   │   │       ├── pantry.py recipes.py meal_plans.py shopping.py
│   │   │       ├── waste.py preservation.py briefings.py streaks.py
│   │   │       ├── youtube.py       # YouTube oEmbed metadata fetch
│   │   │       └── reddit.py blog_importer.py voice.py  # stubs
│   │   ├── alembic/
│   │   │   ├── env.py
│   │   │   └── versions/            # 0001_init_schemas, 0002_create_all_tables
│   │   ├── tests/
│   │   ├── alembic.ini
│   │   ├── pyproject.toml
│   │   └── .env.example
│   └── web/
│       ├── src/
│       │   ├── app/                 # Next.js App Router
│       │   ├── components/
│       │   └── lib/api.ts           # backend API client
│       ├── package.json
│       ├── tsconfig.json
│       └── tailwind.config.ts
├── infra/docker/
│   └── docker-compose.yml           # Postgres
├── docs/
│   └── ARCHITECTURE.md              # Read for deep data-model context
├── packages/shared-types/           # (future) shared TS types
├── frugal                           # one-command dev runner (./frugal up|down)
├── CLAUDE.md                        # This file
├── README.md
└── .gitignore
```

---

## ⚡ Common commands

```bash
# --- The whole stack, one command ---
./frugal up      # Postgres + migrations + backend (:8000) + frontend (:3000)
./frugal down    # stop the dev servers and Postgres

# --- One-time setup (./frugal up handles all of this too) ---
docker compose -f infra/docker/docker-compose.yml up -d
cd apps/backend && uv sync && uv run alembic upgrade head
cd ../web && pnpm install

# --- Or run the pieces by hand ---
# Terminal 1: Postgres (if not already running)
docker compose -f infra/docker/docker-compose.yml up -d

# Terminal 2: Backend
cd apps/backend
uv run uvicorn app.main:app --reload --port 8000

# Terminal 3: Frontend
cd apps/web
pnpm dev   # → http://localhost:3000

# --- Migrations ---
cd apps/backend
uv run alembic revision --autogenerate -m "describe the change"
uv run alembic upgrade head
uv run alembic downgrade -1    # revert last migration

# --- Tests ---
cd apps/backend
uv run pytest

# --- Linting/typing ---
cd apps/backend
uv run ruff check .
uv run ruff format .
uv run mypy app
cd ../web
pnpm typecheck
```

---

## 🐍 Backend conventions

**FastAPI structure.** Routers in `app/routers/<tier>.py`. Each router is a `APIRouter()` mounted in `main.py` with a tier prefix. Routers are thin — they parse input, call a service, return output. **No business logic in routers.**

**Service layer.** Real work happens in `app/services/`. LLM calls in `llm.py`. Domain logic in `services/<feature>.py` when it grows beyond a single function. Services return Python objects (typed Pydantic or dataclasses), not ORM rows directly.

**Models.** SQLAlchemy 2.0 declarative-mapped, with `Mapped[T]` typing. Every domain model inherits `TimestampMixin` (`created_at`, `updated_at`, `deleted_at`). Every domain model has a JSONB `metadata_` column (DB name `metadata`). Use `relationship()` with `back_populates` for bidirectional refs.

**Pydantic.** Request/response schemas in `app/schemas/<tier>.py` (create this as needed). Keep schemas separate from ORM models; never expose models directly.

**Async vs sync.** SQLAlchemy is sync here for simplicity. If/when we hit perf walls, switch to async — but not before measuring.

**Error handling.** Raise `HTTPException` for client errors. Let internal errors propagate and let FastAPI return 500. Don't swallow exceptions silently.

**Logging.** Use Python's stdlib `logging` module, level set via `LOG_LEVEL` env var. Never `print()`.

---

## ⚛️ Frontend conventions

**Next.js 14 App Router.** Routes are folders under `src/app/`. Use Server Components by default; mark client components with `"use client"`. Data fetching via `fetch()` in Server Components or via the `api()` helper in `src/lib/api.ts` from Client Components.

**Styling.** Tailwind utility classes. No CSS modules, no styled-components. Match the existing aesthetic: warm neutrals (stone, amber), generous whitespace, serif headings for warmth contrast.

**Component library.** shadcn/ui when we need primitives (button, dialog, form). Don't pull in Material UI or Chakra.

**State.** React state for local, React Query (TanStack Query) for server state when we add real data. Don't reach for Redux/Zustand prematurely.

**Typing.** Strict TypeScript, no `any`. Shared types between FE and BE go in `packages/shared-types` (currently empty placeholder).

---

## 🤖 LLM patterns

The LLM service is the heart of the product. Read carefully.

**Transport.** `get_client()` returns a CLI-backed shim (`_ClaudeCliClient`) that spawns `claude -p` and exposes the same `.messages.create(...)` surface as the Anthropic SDK. Vision calls write the image to a temp file and let the CLI's Read tool open it. The public functions never see the transport — they call `get_client().messages.create(...)` exactly as before. To revert to the SDK, only `get_client()` changes.

**Model selection** (defined in `app/services/llm.py`):
- `MODEL_FAST` = `claude-sonnet-4-6`. Use for: recipe generation, plan generation, pantry image extraction, anything that's well-scoped and high-volume.
- `MODEL_SMART` = `claude-opus-4-7`. Use for: hard reasoning, multi-constraint optimization (e.g. plan a week of meals balancing pantry + budget + preferences + nutrition), eval generation. Higher cost — use sparingly.
- `MODEL_VISION` = `claude-sonnet-4-6`. Use for: pantry photo extraction. Same model as MODEL_FAST but separated for clarity in case we swap later.

**Structured output.** Always prompt Claude for structured JSON output with an explicit schema, and parse defensively. For Anthropic-recommended JSON output: use a clear schema in the system prompt + "Respond ONLY with valid JSON conforming to the schema; no preamble, no code fences." Validate with Pydantic before returning to callers.

**Prompt versioning.** Each LLM function in `services/llm.py` has a prompt string defined at module level with a version comment (e.g. `# v0.1 — initial extraction prompt`). When you tweak a prompt meaningfully, bump the version and note in the commit message. Eventually move prompts to `app/services/prompts/<name>_v<N>.md` files.

**Cost discipline.** Don't ship a feature whose prompt costs $0.05+ per call without thinking about it. Cache aggressively when the same input recurs (e.g. recipe corpus). When in doubt, use MODEL_FAST.

**Safety guardrails for preservation.** The preservation coach (future) gives advice about home canning, fermentation, etc. **Botulism is a real risk** with low-acid home canning. Any preservation guidance must (a) include safety warnings, (b) reference USDA-aligned guidelines, (c) refuse low-acid water-bath canning advice outright. Bake this into the system prompt for preservation calls.

---

## 🚫 Things NOT to do

- **Don't add tables to `public` schema.** Use `core` or a tier schema.
- **Don't add tier-specific columns to core tables.** Use JSONB metadata or a tier table.
- **Don't `DELETE` from domain tables.** Use soft delete.
- **Don't call Anthropic SDK directly from routers.** Always via `services/llm.py`.
- **Don't introduce a new database, queue, or cache** without checking with the human first. We will need Redis eventually; not yet.
- **Don't add auth UI yet.** Stub user is fine for v1.
- **Don't add a mobile app yet.** Web-first; Expo wraps later.
- **Don't optimize prematurely.** Measure first.
- **Don't add macros/calorie tracking.** MyFitnessPal owns that lane; we're not competing there.
- **Don't pull in heavyweight dependencies casually.** Every new dep is a future maintenance cost.

---

## 📚 When you're stuck or need context

- **Data model deep dive:** `ARCHITECTURE.md` (repo root) — the comprehensive one
- **Setup spec / what was already built:** `frugal_living_setup_instructions.md`
- **Tier expansion playbook:** `ARCHITECTURE.md` → "Adding a new tier"
- **Anthropic SDK reference:** https://docs.claude.com/en/api/overview
- **FastAPI:** https://fastapi.tiangolo.com/
- **SQLAlchemy 2.0:** https://docs.sqlalchemy.org/en/20/
- **Alembic:** https://alembic.sqlalchemy.org/

---

## ✍️ Working style

- **Small, focused commits.** One thing per commit. Conventional commits style: `feat:`, `fix:`, `refactor:`, `chore:`, `docs:`.
- **Test the path you change.** New endpoint? Add a smoke test. New model? Add a migration roundtrip test.
- **Ask before refactoring at scale.** If your change touches more than three files unrelated to the task, stop and check with the human.
- **Default to the simplest design that satisfies the inviolable rules.** Cleverness is debt.
- **Surface tradeoffs.** When two reasonable approaches exist, name both and recommend one with reasoning.

---

End of memory. When in doubt, re-read the 7 rules.
