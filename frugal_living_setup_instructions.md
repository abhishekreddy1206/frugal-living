# frugal-living — Cowork Project Setup Instructions

> **For Cowork:** This document is a complete, executable spec for setting up the `frugal-living` project locally on macOS or Linux. Follow each step in order. Each section is self-contained. Where commands appear in code blocks, run them in a terminal. Where file contents appear, create those files at the indicated paths with the indicated contents.
>
> **For Abhishek (the human):** This sets up Tier A (food/pantry) with a data schema designed to absorb Tier S (medical/bills/tax) and Tier B (community) later without breaking changes. The MVP focus is the three highest-priority features: **(1) pantry capture, (2) recipe stretching, (3) meal planning**. Everything else is scaffolded but not implemented.

---

## 0. Architectural decisions (read this first)

**Stack:**
- **Backend:** Python 3.11+ / FastAPI / SQLAlchemy 2.0 / Alembic / PostgreSQL 16
- **Frontend:** Next.js 14 (App Router) / TypeScript / Tailwind / shadcn/ui
- **AI:** Anthropic Claude API (Sonnet 4.6 for fast paths, Opus 4.7 for hard reasoning) + Claude vision for pantry capture
- **Local dev DB:** Postgres via Docker Compose (NOT SQLite — we use Postgres-specific features like JSONB and arrays)
- **Auth:** Stub for now (single dev user); plug in Clerk or Auth.js when needed
- **Package mgmt:** `uv` for Python (much faster than pip), `pnpm` for JS

**Why this stack:**
- Postgres JSONB columns let us add tier-specific fields without schema migrations on the core tables.
- A monorepo (apps/backend, apps/web) lets us add `apps/mobile` (Expo) later without restructuring.
- FastAPI's modular router pattern lets each tier mount its own routes (`/api/v1/food/*`, `/api/v1/bills/*`, `/api/v1/community/*`) cleanly.
- The data model uses **module tables** (one per tier feature) instead of a single mega-schema, so Tier S and Tier B additions are isolated.

**Future-proofing principles encoded in the schema:**
1. **Core entities are tier-agnostic.** `users`, `households`, `household_members`, `subscriptions`, `feature_flags`, `audit_log` are shared across all tiers and never reference tier-specific tables.
2. **Each tier has its own schema namespace.** Postgres schemas: `core`, `food`, `bills` (future), `health` (future), `community` (future). New tiers add a schema, not new tables in `public`.
3. **JSONB `metadata` on every table.** Lets us add fields per row without migrations. Index selectively as fields become hot.
4. **Soft delete + audit log.** Every domain table has `deleted_at`, and every mutation logs to `core.audit_log`. Critical for trust + debugging + future GDPR/CCPA compliance.
5. **Polymorphic attachments / events.** A single `core.events` table records household-level activity (pantry item added, meal cooked, bill negotiated) keyed by `entity_type + entity_id`. Lets new tiers emit events without touching core code.

---

## 1. Prerequisites

Cowork should verify these are installed. If any are missing, install them.

```bash
# Check versions
python3 --version    # need 3.11+
node --version       # need 20+
docker --version     # need 24+
git --version        # any modern version

# Install if missing (macOS via Homebrew)
brew install python@3.11 node docker git uv pnpm
```

If on Linux, use the system package manager. If `uv` or `pnpm` aren't available:
```bash
# uv (fast Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# pnpm
npm install -g pnpm
```

---

## 2. Create the project structure

```bash
# Pick your projects directory; adjust as needed
cd ~/projects
mkdir frugal-living
cd frugal-living

# Initialize git
git init
git branch -M main

# Create the monorepo structure
mkdir -p apps/backend/app
mkdir -p apps/backend/alembic/versions
mkdir -p apps/backend/tests
mkdir -p apps/web/src/app
mkdir -p apps/web/src/components
mkdir -p apps/web/src/lib
mkdir -p packages/shared-types
mkdir -p infra/docker
mkdir -p docs
```

---

## 3. Root files

### `.gitignore`
```
# Python
__pycache__/
*.py[cod]
*$py.class
.venv/
venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/

# Node
node_modules/
.next/
out/
.turbo/
.pnpm-store/

# Env
.env
.env.local
.env.*.local
!.env.example

# Editors
.vscode/
.idea/
.DS_Store

# Build artifacts
dist/
build/
*.egg-info/

# Local DB volumes
postgres-data/

# Logs
*.log
```

### `README.md`
```markdown
# frugal-living

An AI-native suite for households living well on less. Working name: Hearth.

## Quick start

```bash
# 1. Start Postgres
docker compose -f infra/docker/docker-compose.yml up -d

# 2. Backend
cd apps/backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

# 3. Frontend (separate terminal)
cd apps/web
pnpm install
pnpm dev
```

Open http://localhost:3000

## Tier roadmap

- **Tier A (now)** — food/pantry/preservation
- **Tier S (later)** — bills, medical, tax, insurance
- **Tier B (later)** — community, sharing, repair

See `docs/architecture.md` for data-model details.
```

### `docker-compose.yml` at `infra/docker/docker-compose.yml`
```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: frugal
      POSTGRES_PASSWORD: frugal_dev
      POSTGRES_DB: frugal_living
    ports:
      - "5432:5432"
    volumes:
      - ../../postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U frugal -d frugal_living"]
      interval: 5s
      timeout: 5s
      retries: 5
```

---

## 4. Backend setup

### `apps/backend/pyproject.toml`
```toml
[project]
name = "frugal-living-backend"
version = "0.1.0"
description = "Frugal Living API"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "sqlalchemy>=2.0.36",
  "alembic>=1.14",
  "psycopg[binary]>=3.2",
  "pydantic>=2.10",
  "pydantic-settings>=2.6",
  "python-dotenv>=1.0",
  "anthropic>=0.42",
  "httpx>=0.28",
  "python-multipart>=0.0.12",
  "passlib[bcrypt]>=1.7",
  "python-jose[cryptography]>=3.3",
]

[tool.uv]
dev-dependencies = [
  "pytest>=8.3",
  "pytest-asyncio>=0.24",
  "ruff>=0.8",
  "mypy>=1.13",
]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "W", "UP", "B"]
```

### `apps/backend/.env.example`
```
DATABASE_URL=postgresql+psycopg://frugal:frugal_dev@localhost:5432/frugal_living
ANTHROPIC_API_KEY=sk-ant-your-key-here
JWT_SECRET=change-me-in-prod
ENV=local
LOG_LEVEL=INFO
```

After creating, Cowork should run:
```bash
cd apps/backend
cp .env.example .env
# (Abhishek will paste real ANTHROPIC_API_KEY into .env manually)
```

### `apps/backend/app/__init__.py`
```python
```
(empty file)

### `apps/backend/app/config.py`
```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    anthropic_api_key: str
    jwt_secret: str = "change-me"
    env: str = "local"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


settings = Settings()
```

### `apps/backend/app/db.py`
```python
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
```

### `apps/backend/app/models/__init__.py`
```python
# Import all model modules so Alembic autogenerate sees them.
from app.models import core  # noqa: F401
from app.models import food  # noqa: F401
# from app.models import bills      # add when Tier S ships
# from app.models import health     # add when Tier S ships
# from app.models import community  # add when Tier B ships
```

### `apps/backend/app/models/core.py` — shared across all tiers
```python
"""
Core models — shared across all tiers (Tier A food, Tier S bills/health, Tier B community).
Do NOT add tier-specific fields here. Use the `metadata_` JSONB column for transient extension.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import (
    String, DateTime, Boolean, ForeignKey, Integer, Text, func, Index
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    household_memberships: Mapped[list[HouseholdMember]] = relationship(back_populates="user")


class Household(Base, TimestampMixin):
    __tablename__ = "households"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    size: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    locale: Mapped[str] = mapped_column(String(10), default="en-US", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="America/Los_Angeles", nullable=False)
    # Free-form fields: dietary restrictions, equipment list, preferences, etc.
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    members: Mapped[list[HouseholdMember]] = relationship(back_populates="household")


class HouseholdMember(Base, TimestampMixin):
    __tablename__ = "household_members"
    __table_args__ = (
        Index("idx_household_members_user", "user_id"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), default="owner", nullable=False)  # owner | member

    household: Mapped[Household] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="household_memberships")


class Subscription(Base, TimestampMixin):
    """Single subscription per user spans access to ALL tiers via tier flags."""
    __tablename__ = "subscriptions"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=False, unique=True
    )
    plan: Mapped[str] = mapped_column(String(32), default="free", nullable=False)  # free | pro | suite
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    tier_a_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tier_s_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tier_b_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    renews_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class FeatureFlag(Base, TimestampMixin):
    """Server-side feature flags. Lets new tier features ship dark, then enabled per cohort."""
    __tablename__ = "feature_flags"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled_globally: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rollout_percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 0..100
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class Event(Base):
    """
    Polymorphic activity log. Every meaningful action across any tier writes here.
    Lets us build streaks, undo, audit, analytics without coupling tiers.
    """
    __tablename__ = "events"
    __table_args__ = (
        Index("idx_events_household", "household_id", "created_at"),
        Index("idx_events_entity", "entity_type", "entity_id"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # e.g. "food.pantry_item.added", "bills.negotiation.completed", "community.swap.matched"
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuditLog(Base):
    """Separate from events: tracks WHO did what, including admin/system actions."""
    __tablename__ = "audit_log"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

### `apps/backend/app/models/food.py` — Tier A (MVP focus)
```python
"""
Food tier — pantry, recipes, meal planning, preservation, food waste, shopping.
This is Tier A. All tables live in the `food` schema.
"""
from __future__ import annotations

import uuid
from datetime import datetime, date
from sqlalchemy import (
    String, DateTime, Date, ForeignKey, Integer, Numeric, Text, Index, Boolean, func
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.core import TimestampMixin


# ---------- Canonical ingredient catalog ----------

class Ingredient(Base, TimestampMixin):
    """Canonical ingredient table. Shared across recipes, pantry, shopping lists."""
    __tablename__ = "ingredients"
    __table_args__ = (
        Index("idx_ingredients_canonical", "canonical_name"),
        {"schema": "food"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_name: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # protein, grain, dairy, produce, condiment, spice, oil, baking, beverage, frozen, other
    default_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    typical_shelf_life_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


# ---------- Pantry (Priority 1) ----------

class PantryLocation(Base, TimestampMixin):
    """Where things are stored — main pantry, fridge, freezer, root cellar, etc."""
    __tablename__ = "pantry_locations"
    __table_args__ = {"schema": "food"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    location_type: Mapped[str] = mapped_column(String(32), default="pantry", nullable=False)
    # pantry | fridge | freezer | root_cellar | spice_rack | other
    temperature_c: Mapped[float | None] = mapped_column(Numeric(4, 1), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class PantryItem(Base, TimestampMixin):
    """A unit of food currently in the household. Captured via photo, receipt, or manual."""
    __tablename__ = "pantry_items"
    __table_args__ = (
        Index("idx_pantry_household_expires", "household_id", "expires_at"),
        Index("idx_pantry_ingredient", "ingredient_id"),
        {"schema": "food"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.pantry_locations.id"), nullable=True
    )
    ingredient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.ingredients.id"), nullable=True
    )
    raw_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # raw text as captured, before canonical resolution

    quantity: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    purchased_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    opened_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    estimated_value: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    # manual | photo_capture | receipt_scan | imported
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    # 0..1 — for AI-captured items
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


# ---------- Recipes (Priority 2: Recipe Stretcher) ----------

class Recipe(Base, TimestampMixin):
    __tablename__ = "recipes"
    __table_args__ = {"schema": "food"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(220), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_attribution: Mapped[str | None] = mapped_column(String(200), nullable=True)
    servings: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    prep_time_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cook_time_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cuisine: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    difficulty: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    estimated_cost_per_serving_usd: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    is_user_created: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=True
    )
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    ingredients: Mapped[list[RecipeIngredient]] = relationship(back_populates="recipe", cascade="all, delete-orphan")
    steps: Mapped[list[RecipeStep]] = relationship(back_populates="recipe", cascade="all, delete-orphan")


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"
    __table_args__ = {"schema": "food"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.recipes.id", ondelete="CASCADE"), nullable=False
    )
    ingredient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.ingredients.id"), nullable=True
    )
    raw_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    substitutions: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    recipe: Mapped[Recipe] = relationship(back_populates="ingredients")


class RecipeStep(Base):
    __tablename__ = "recipe_steps"
    __table_args__ = {"schema": "food"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.recipes.id", ondelete="CASCADE"), nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    recipe: Mapped[Recipe] = relationship(back_populates="steps")


# ---------- Meal planning (Priority 3) ----------

class MealPlan(Base, TimestampMixin):
    __tablename__ = "meal_plans"
    __table_args__ = {"schema": "food"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False, index=True
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    target_budget_usd: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)
    # draft | active | archived
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    meals: Mapped[list[PlannedMeal]] = relationship(back_populates="meal_plan", cascade="all, delete-orphan")


class PlannedMeal(Base, TimestampMixin):
    __tablename__ = "planned_meals"
    __table_args__ = {"schema": "food"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meal_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.meal_plans.id", ondelete="CASCADE"), nullable=False
    )
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.recipes.id"), nullable=True
    )
    planned_date: Mapped[date] = mapped_column(Date, nullable=False)
    meal_type: Mapped[str] = mapped_column(String(16), default="dinner", nullable=False)
    # breakfast | lunch | dinner | snack
    servings: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="planned", nullable=False)
    # planned | prepped | cooked | skipped
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    meal_plan: Mapped[MealPlan] = relationship(back_populates="meals")


# ---------- Shopping ----------

class ShoppingList(Base, TimestampMixin):
    __tablename__ = "shopping_lists"
    __table_args__ = {"schema": "food"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False, index=True
    )
    meal_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.meal_plans.id"), nullable=True
    )
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class ShoppingItem(Base, TimestampMixin):
    __tablename__ = "shopping_items"
    __table_args__ = {"schema": "food"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shopping_list_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.shopping_lists.id", ondelete="CASCADE"), nullable=False
    )
    ingredient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.ingredients.id"), nullable=True
    )
    raw_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    store: Mapped[str | None] = mapped_column(String(120), nullable=True)
    estimated_price_usd: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    actual_price_usd: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    # pending | purchased | skipped


# ---------- Preservation (Tier A expansion) ----------

class PreservationJob(Base, TimestampMixin):
    """Canning, freezing, dehydrating, fermenting, pickling. Has safety constraints."""
    __tablename__ = "preservation_jobs"
    __table_args__ = {"schema": "food"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False, index=True
    )
    source_pantry_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.pantry_items.id"), nullable=True
    )
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    # canning_water_bath | canning_pressure | freezing | dehydrating | fermenting | pickling | curing
    ingredient_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity_in: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    quantity_out: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    storage_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.pantry_locations.id"), nullable=True
    )
    expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    safety_check_passed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    safety_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_urls: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


# ---------- Food waste tracking ----------

class FoodWasteEvent(Base, TimestampMixin):
    __tablename__ = "food_waste_events"
    __table_args__ = {"schema": "food"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False, index=True
    )
    pantry_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("food.pantry_items.id"), nullable=True
    )
    ingredient_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # spoiled | forgotten | over_cooked | over_purchased | other
    estimated_value_usd: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
```

### `apps/backend/alembic.ini` at `apps/backend/alembic.ini`
```ini
[alembic]
script_location = alembic
sqlalchemy.url = postgresql+psycopg://frugal:frugal_dev@localhost:5432/frugal_living

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

### `apps/backend/alembic/env.py`
```python
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

from app.config import settings
from app.db import Base
import app.models  # noqa: F401 — ensures all models register

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, include_schemas=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

### `apps/backend/alembic/script.py.mako`
```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

### `apps/backend/alembic/versions/0001_init_schemas.py` — manually-created seed migration
```python
"""init schemas

Revision ID: 0001
Revises:
Create Date: 2026-05-18

"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS core")
    op.execute("CREATE SCHEMA IF NOT EXISTS food")
    # Future:
    # op.execute("CREATE SCHEMA IF NOT EXISTS bills")
    # op.execute("CREATE SCHEMA IF NOT EXISTS health")
    # op.execute("CREATE SCHEMA IF NOT EXISTS community")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS food CASCADE")
    op.execute("DROP SCHEMA IF EXISTS core CASCADE")
```

### `apps/backend/app/main.py`
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import food, health

app = FastAPI(title="Frugal Living API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(food.router, prefix="/api/v1/food", tags=["food"])
# Future:
# app.include_router(bills.router, prefix="/api/v1/bills", tags=["bills"])
# app.include_router(community.router, prefix="/api/v1/community", tags=["community"])


@app.get("/")
def root():
    return {"name": "frugal-living", "version": "0.1.0", "tier_a": True}
```

### `apps/backend/app/routers/__init__.py`
```python
```
(empty)

### `apps/backend/app/routers/health.py`
```python
from fastapi import APIRouter
from sqlalchemy import text

from app.db import engine

router = APIRouter()


@router.get("/healthz")
def healthz():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "db": "ok"}
    except Exception as e:
        return {"status": "degraded", "db": "error", "error": str(e)}
```

### `apps/backend/app/routers/food.py`
```python
"""Stub routes for Tier A. Flesh out as MVP features land."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter()


@router.get("/pantry")
def list_pantry(db: Session = Depends(get_db)):
    # TODO: filter by household_id from auth context
    return {"items": [], "todo": "Wire to PantryItem model"}


@router.post("/pantry/capture")
def capture_pantry(db: Session = Depends(get_db)):
    """Photo-to-pantry: takes an image, returns extracted items.
    Will call Claude vision with a structured-output prompt.
    """
    return {"items": [], "todo": "Wire to Claude vision"}


@router.get("/recipes/stretch")
def stretch_recipes(db: Session = Depends(get_db)):
    """Given current pantry, suggest meals using what's about to expire."""
    return {"suggestions": [], "todo": "Wire to Claude with pantry context"}


@router.post("/meal-plans/generate")
def generate_meal_plan(db: Session = Depends(get_db)):
    """Generate a weekly meal plan optimized for pantry, budget, preferences."""
    return {"meal_plan": None, "todo": "Wire to Claude + pantry + recipes"}


@router.get("/preservation/methods")
def preservation_methods():
    """Static catalog of safe preservation methods per ingredient."""
    return {"methods": [], "todo": "Seed from USDA-aligned catalog"}
```

### `apps/backend/app/services/__init__.py`
```python
```
(empty)

### `apps/backend/app/services/llm.py`
```python
"""Centralized Claude client. Every tier uses this."""
from anthropic import Anthropic
from app.config import settings

client = Anthropic(api_key=settings.anthropic_api_key)

# Model selection by job:
MODEL_FAST = "claude-sonnet-4-6"      # routine recipe generation, planning
MODEL_SMART = "claude-opus-4-7"        # hard reasoning, multi-constraint optimization
MODEL_VISION = "claude-sonnet-4-6"     # pantry photo extraction


def extract_pantry_from_image(image_base64: str, media_type: str = "image/jpeg") -> dict:
    """Stub. Implement structured-output prompt for pantry capture."""
    raise NotImplementedError("Implement in MVP sprint 1")


def stretch_recipes_for_pantry(pantry_items: list[dict], constraints: dict) -> list[dict]:
    """Stub. Generate recipes optimized for what's on hand + budget + preferences."""
    raise NotImplementedError("Implement in MVP sprint 2")


def generate_weekly_plan(household: dict, pantry: list[dict], constraints: dict) -> dict:
    """Stub. Generate 5-7 meals planned around pantry + budget."""
    raise NotImplementedError("Implement in MVP sprint 3")
```

---

## 5. Frontend setup

### `apps/web/package.json`
```json
{
  "name": "frugal-living-web",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "next lint",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "next": "14.2.18",
    "react": "18.3.1",
    "react-dom": "18.3.1"
  },
  "devDependencies": {
    "@types/node": "22.10.1",
    "@types/react": "18.3.12",
    "@types/react-dom": "18.3.1",
    "autoprefixer": "10.4.20",
    "postcss": "8.4.49",
    "tailwindcss": "3.4.16",
    "typescript": "5.7.2",
    "eslint": "9.16.0",
    "eslint-config-next": "14.2.18"
  }
}
```

### `apps/web/tsconfig.json`
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": { "@/*": ["./src/*"] }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

### `apps/web/next.config.mjs`
```javascript
const nextConfig = {
  reactStrictMode: true,
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  },
};
export default nextConfig;
```

### `apps/web/tailwind.config.ts`
```typescript
import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: { extend: {} },
  plugins: [],
};
export default config;
```

### `apps/web/postcss.config.mjs`
```javascript
export default { plugins: { tailwindcss: {}, autoprefixer: {} } };
```

### `apps/web/src/app/globals.css`
```css
@tailwind base;
@tailwind components;
@tailwind utilities;

body { @apply bg-stone-50 text-stone-900; }
```

### `apps/web/src/app/layout.tsx`
```typescript
import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Frugal Living",
  description: "Live well on less.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
```

### `apps/web/src/app/page.tsx`
```typescript
export default function Home() {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center p-10">
      <h1 className="text-4xl font-bold text-stone-900">frugal-living</h1>
      <p className="mt-2 text-stone-600">An AI-native suite for living well on less.</p>
      <p className="mt-8 text-sm text-stone-500">
        Tier A in progress · Pantry · Recipes · Meal Planning
      </p>
    </main>
  );
}
```

### `apps/web/src/lib/api.ts`
```typescript
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json();
}
```

---

## 6. Execute setup (commands Cowork should run in order)

```bash
# From repo root
cd ~/projects/frugal-living

# Start Postgres
docker compose -f infra/docker/docker-compose.yml up -d

# Wait for Postgres healthcheck
sleep 5

# --- Backend ---
cd apps/backend
uv sync
uv run alembic upgrade head

# Generate the initial domain migration from the models
uv run alembic revision --autogenerate -m "tier_a_food_models"
uv run alembic upgrade head

# Smoke-test the API
uv run uvicorn app.main:app --reload --port 8000 &
sleep 3
curl -s http://localhost:8000/healthz | head
# Should print something like {"status":"ok","db":"ok"}

# --- Frontend (new terminal or background) ---
cd ../web
pnpm install
pnpm dev &
sleep 5
# Frontend will be at http://localhost:3000

# --- Git ---
cd ../..
git add -A
git commit -m "feat: initial scaffold with Tier A data models"
```

---

## 7. How to add a future tier (Tier S example)

When you ship Tier S (medical bills, etc.), follow this pattern — no breaking changes to core:

1. Create the schema in a new migration:
   ```sql
   CREATE SCHEMA IF NOT EXISTS bills;
   CREATE SCHEMA IF NOT EXISTS health;
   ```
2. Add `apps/backend/app/models/bills.py` and `apps/backend/app/models/health.py`. Mirror the food.py pattern: all tables in their own schema, FK to `core.households(id)` and `core.users(id)`, JSONB `metadata` for transient extension.
3. Register the modules in `apps/backend/app/models/__init__.py`.
4. Add routers at `apps/backend/app/routers/bills.py`, mount under `/api/v1/bills`.
5. Flip the `tier_s_enabled` flag on user subscriptions to gate UI.
6. Run `alembic revision --autogenerate -m "tier_s_bills_health_models"` then `alembic upgrade head`.

The `core.events` table absorbs all new event types automatically (just emit `bills.negotiation.completed` etc.). No core changes ever needed for new tiers.

---

## 8. Sprint 1 backlog (what to build first inside Tier A)

These are the three highest-priority MVP features. Each is roughly 1–2 weeks of focused work.

**Sprint 1 — Pantry capture**
- `POST /api/v1/food/pantry/capture` — accepts image, returns extracted items
- Wire `services/llm.py::extract_pantry_from_image` to Claude vision with structured output (JSON schema for items)
- Frontend: a single page with camera/upload + confirmation list

**Sprint 2 — Recipe stretcher**
- `GET /api/v1/food/recipes/stretch` — given current pantry, return 3–5 meal ideas
- Wire `services/llm.py::stretch_recipes_for_pantry`
- Frontend: "What can I make right now?" button on home

**Sprint 3 — Weekly meal plan**
- `POST /api/v1/food/meal-plans/generate` — given pantry + budget, return 5–7 dinners
- Wire `services/llm.py::generate_weekly_plan`
- Frontend: weekly calendar view with planned meals

Everything else in Tier A (preservation, shopping list, waste tracking, multi-user household) is post-Sprint 3.

---

## 9. Important non-goals for v1

- No auth UI yet (use a dev-mode header that injects a fixed user_id).
- No payments yet.
- No mobile app yet (web first; Expo can wrap later).
- No social/community features.
- No grocery delivery integration (affiliate only).

---

## 10. Notes for Cowork on common failure modes

- **Docker Postgres won't start:** check port 5432 isn't already taken (`lsof -i :5432`). Stop any local Postgres.
- **`alembic upgrade head` fails with "schema does not exist":** Make sure migration `0001_init_schemas.py` runs before the autogenerated migration. The order matters.
- **`uv sync` fails:** verify Python 3.11+ is available; `uv python install 3.11` if not.
- **CORS errors in frontend:** the backend allows `localhost:3000` by default. If using a different port, update `app/main.py`.
- **Anthropic API key missing:** the backend will start but any LLM call will fail. Put your key in `apps/backend/.env`.

---

## 11. What's intentionally simple

- Authentication is stubbed. Replace with Clerk or Auth.js before any real users.
- No background job queue yet. Add Celery or RQ when you need async pantry image processing at scale.
- No caching layer yet. Redis goes between API and Claude for prompt caching when costs start mattering.
- No file storage. Pantry photos live as base64 in requests for now; add S3/R2 when you need to keep them.

Each of these is a "deliberately deferred" decision, not an oversight. Defer until usage forces the upgrade.

---

End of spec. Cowork: execute Sections 1 through 6 in order. Sections 7–11 are reference for the human.
