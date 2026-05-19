# frugal-living

An AI-native suite for households living well on less. Working name: **Hearth**.

## Quick start

```bash
# 1. Start Postgres
docker compose -f infra/docker/docker-compose.yml up -d

# 2. Backend
cd apps/backend
cp .env.example .env  # then paste your ANTHROPIC_API_KEY
uv sync
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "domain_models"
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

# 3. Frontend (separate terminal)
cd apps/web
pnpm install
pnpm dev
```

Open http://localhost:3000

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
  architecture.md Tier model, content ingestion, AI surfaces, tracking
```

## Tier roadmap

- **Tier A (now)** — food, pantry, recipes, meal planning, preservation, waste tracking
- **Tier S (later)** — bills, medical, tax, insurance
- **Tier B (later)** — community, sharing, repair

## Cross-cutting modules (all tiers)

- `content` — curated YouTube/blog/Reddit ingestion + AI-generated articles
- `ai` — Claude conversations, voice sessions, daily briefings
- `tracking` — savings dashboard (budgets, spend, waste value) + streaks/badges

See `docs/architecture.md` for the data-model details and the rule for adding a new tier without breaking changes.
