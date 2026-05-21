# frugal-living

An AI-native suite for households living well on less. Working name: **Hearth**.

## Quick start

```bash
cp apps/backend/.env.example apps/backend/.env   # DATABASE_URL is enough
./frugal up
```

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
cd apps/backend && uv run pytest      # 134 backend tests
cd apps/web && pnpm typecheck         # frontend type check
```

## What's built

Tier A is implemented end-to-end: pantry photo capture, recipe stretcher,
weekly meal plan, shopping lists, waste tracking, and a preservation coach,
plus daily AI briefings, a streaks/badges tracker, and YouTube link capture
(the `/watch` library). Channel/RSS/Reddit ingestion is still stubbed. See
`CLAUDE.md` for the current-state breakdown.

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

- **Tier A (now)** — food, pantry, recipes, meal planning, preservation, waste tracking
- **Tier S (later)** — bills, medical, tax, insurance
- **Tier B (later)** — community, sharing, repair

## Cross-cutting modules (all tiers)

- `content` — curated YouTube/blog/Reddit ingestion + AI-generated articles
- `ai` — Claude conversations, voice sessions, daily briefings
- `tracking` — savings dashboard (budgets, spend, waste value) + streaks/badges

See `ARCHITECTURE.md` for the data-model deep dive and the playbook for adding a
new tier without breaking changes; `docs/architecture.md` covers the cross-cutting
modules and AI surfaces.
