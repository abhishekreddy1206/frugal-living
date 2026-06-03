# frugal-living

An AI-native suite for households living well on less. Working name: **Hearth**.

## Quick start

```bash
cp apps/backend/.env.example apps/backend/.env   # DATABASE_URL is enough to boot
./frugal up
```

`DATABASE_URL` is all you need locally. For a real deployment, also set a
`JWT_SECRET`; optionally set `ADMIN_EMAIL` / `ADMIN_PASSWORD` /
`ADMIN_DISPLAY_NAME` to bootstrap an admin user on startup.

`./frugal up` starts Postgres, applies migrations, and launches the backend
(:8000) and frontend (:3000). Open http://localhost:3000. `./frugal down`
stops everything. First run installs deps automatically.

Prerequisites: Docker, [`uv`](https://docs.astral.sh/uv/), `pnpm`, and the
Claude Code CLI (`claude`) installed and logged in — the AI layer shells out
to the CLI, so no `ANTHROPIC_API_KEY` is needed. See `CLAUDE.md` →
"LLM patterns" for the transport details.

<details>
<summary>Running the pieces by hand</summary>

```bash
docker compose -f infra/docker/docker-compose.yml up -d
cd apps/backend && uv sync && uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
cd ../web && pnpm install && pnpm dev
```
</details>

## Tests

```bash
cd apps/backend && uv run pytest      # ~409 backend tests (need Postgres + claude CLI)
cd apps/web && pnpm typecheck         # frontend type check
```

## What's built

Tier A is implemented end-to-end: pantry photo capture, recipe stretcher,
weekly meal plan, shopping lists, waste tracking, and a preservation coach,
plus daily AI briefings, a conversational chat assistant, a streaks/badges
tracker, and YouTube link capture (the `/watch` library).

Beyond Tier A, the app now has **real cookie-session auth** (signup/login,
password hashing, login throttling, multi-household support, and household
invites), the **full Tier B community suite** (durable-goods inventory,
hyperlocal communities, join requests, and listings/sharing), and an **admin
console** (user management, content moderation, feature flags, and a
global→household→user settings resolver).

Still stubbed: channel/RSS/Reddit ingestion, voice, and the tracking
dashboard/savings/budgets endpoints. See `CLAUDE.md` for the full
current-state breakdown.

## Monorepo layout

```
apps/
  backend/        FastAPI + SQLAlchemy + Alembic + Postgres
  web/            Next.js 14 (App Router) + Tailwind
  mobile/         (placeholder) Expo React Native — future
packages/
  shared-types/   TypeScript types shared between web and mobile
infra/
  docker/         docker-compose.yml for local Postgres
docs/
  architecture.md Cross-cutting modules (content/ai/tracking), AI surfaces
ARCHITECTURE.md   Data-model deep dive (core + food schemas, events, migrations)
CLAUDE.md         Project guide + current-state breakdown
```

## Tier roadmap

- **Tier A (built)** — food, pantry, recipes, meal planning, preservation, waste tracking
- **Tier B (built)** — community: durable-goods inventory, hyperlocal communities, listings/sharing
- **Tier S (later)** — bills, medical, tax, insurance

## Cross-cutting modules (all tiers)

- `content` — YouTube link capture + AI enrichment/pantry-fit ranking (RSS/Reddit ingestion stubbed)
- `ai` — Claude conversations + daily briefings (voice still stubbed)
- `tracking` — streaks/badges (live); savings dashboard + budgets (stubbed)

See `ARCHITECTURE.md` for the data-model deep dive and the playbook for adding a
new tier without breaking changes; `docs/architecture.md` covers the cross-cutting
modules and AI surfaces.
