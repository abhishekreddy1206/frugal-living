# Phase 1 — Household Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single-household catalog of durable possessions (the `community` schema's first feature) with photo capture, REST CRUD, events, an `/inventory` page, and full AI chat parity.

**Architecture:** New `community` Postgres schema with one `community.items` table, following the Tier A patterns exactly — a SQLAlchemy model, hand-written Alembic migration, a Pydantic schema module, a `services/community/` package, a thin router mounted at `/api/v1/community`, and `community.item.*` events. The AI chat assistant gains an `inventory` page scope with grounding context and three new actions, wired additively into the existing `services/chat.py`.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy 2.0 / Alembic / PostgreSQL 16 / pytest (backend); Next.js 14 / TypeScript / Tailwind (frontend). Package managers: `uv` (backend), `pnpm` (frontend).

**Spec:** `docs/superpowers/specs/2026-05-21-phase-1-household-inventory-design.md`

All backend commands run from `apps/backend/`; all frontend commands from `apps/web/`. Postgres must be running (`./frugal up` or `docker compose -f infra/docker/docker-compose.yml up -d`).

---

### Task 1: `CommunityItem` model + `community` schema migration

**Files:**
- Create: `apps/backend/app/models/community.py`
- Modify: `apps/backend/app/models/__init__.py`
- Create: `apps/backend/alembic/versions/0003_community_items.py`
- Modify: `apps/backend/tests/conftest.py`
- Test: `apps/backend/tests/test_community_models.py`

- [ ] **Step 1: Create the model**

Create `apps/backend/app/models/community.py`:

```python
"""
Community tier — Tier B. Phase 1: a single-household inventory of durable
possessions. All tables live in the `community` schema.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime  # noqa: F401 — datetime used via TimestampMixin typing

from sqlalchemy import Date, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.core import TimestampMixin


class CommunityItem(Base, TimestampMixin):
    """A durable possession a household owns — game, tool, book, gear.

    Per-unit: one row is one thing. `quantity` covers genuinely fungible bulk
    (e.g. "8 folding chairs") without forcing eight rows.
    """

    __tablename__ = "items"
    __table_args__ = (
        Index("idx_items_household_category", "household_id", "category"),
        {"schema": "community"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="other", nullable=False)
    # tools | games | books | kitchen | outdoor | electronics | furniture | kids | sports | other
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    condition: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # new | like_new | good | fair | poor
    estimated_value_usd: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    location: Mapped[str | None] = mapped_column(String(120), nullable=True)
    acquired_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    # manual | photo_capture | chat
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
```

- [ ] **Step 2: Register the model so Alembic and the ORM see it**

In `apps/backend/app/models/__init__.py`, replace the entire file with:

```python
# Import all model modules so Alembic autogenerate sees them.
from app.models import (
    ai,  # noqa: F401
    community,  # noqa: F401
    content,  # noqa: F401
    core,  # noqa: F401
    food,  # noqa: F401
    tracking,  # noqa: F401
)
# from app.models import bills      # add when Tier S ships
# from app.models import health     # add when Tier S ships
```

- [ ] **Step 3: Write the migration**

Create `apps/backend/alembic/versions/0003_community_items.py`:

```python
"""community schema + items table

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-22

"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS community")
    op.create_table(
        "items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("condition", sa.String(length=16), nullable=True),
        sa.Column("estimated_value_usd", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("location", sa.String(length=120), nullable=True),
        sa.Column("acquired_on", sa.Date(), nullable=True),
        sa.Column("photo_url", sa.String(length=500), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["household_id"], ["core.households.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["core.users.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="community",
    )
    op.create_index(
        "idx_items_household_category",
        "items",
        ["household_id", "category"],
        unique=False,
        schema="community",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_items_household_category", table_name="items", schema="community"
    )
    op.drop_table("items", schema="community")
    op.execute("DROP SCHEMA IF EXISTS community CASCADE")
```

- [ ] **Step 4: Apply the migration**

Run: `uv run alembic upgrade head`
Expected: output ends with `Running upgrade 0002 -> 0003, community schema + items table`.

- [ ] **Step 5: Add `community.items` cleanup to the test fixture**

In `apps/backend/tests/conftest.py`, add this import alongside the other model imports (after the `from app.models.core import Event` line):

```python
from app.models.community import CommunityItem
```

Then inside the `_clean_household_data` fixture, add this line immediately after the `PantryItem` delete line:

```python
        db_.query(CommunityItem).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
```

- [ ] **Step 6: Write the failing test**

Create `apps/backend/tests/test_community_models.py`:

```python
"""Model-level tests for the community inventory table."""
from __future__ import annotations

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.community import CommunityItem


def test_community_item_roundtrip(db):
    item = CommunityItem(
        household_id=DEV_HOUSEHOLD_ID,
        created_by_user_id=DEV_USER_ID,
        name="Catan",
        category="games",
    )
    db.add(item)
    db.flush()

    fetched = db.get(CommunityItem, item.id)
    assert fetched is not None
    assert fetched.name == "Catan"
    assert fetched.category == "games"
    # Server/Python defaults applied.
    assert fetched.quantity == 1
    assert fetched.tags == []
    assert fetched.source == "manual"
    assert fetched.metadata_ == {}
    assert fetched.deleted_at is None
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `uv run pytest tests/test_community_models.py -v`
Expected: PASS (the model and table now exist).

- [ ] **Step 8: Commit**

```bash
git add apps/backend/app/models/community.py apps/backend/app/models/__init__.py \
  apps/backend/alembic/versions/0003_community_items.py apps/backend/tests/conftest.py \
  apps/backend/tests/test_community_models.py
git commit -m "feat(community): add CommunityItem model and community schema migration"
```

---

### Task 2: Community Pydantic schemas

**Files:**
- Create: `apps/backend/app/schemas/community.py`
- Test: `apps/backend/tests/test_community_schemas.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_community_schemas.py`:

```python
"""Schema validation tests for the community tier."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.community import ExtractedInventory, ItemCreate, ItemUpdate


def test_item_create_rejects_unknown_category():
    with pytest.raises(ValidationError):
        ItemCreate(name="Drill", category="vehicles")


def test_item_create_defaults():
    item = ItemCreate(name="Catan")
    assert item.category == "other"
    assert item.tags == []
    assert item.quantity == 1


def test_item_update_all_optional():
    # An empty update is valid — every field is optional.
    ItemUpdate()


def test_extracted_inventory_parses_permissive_category():
    # The vision path is untrusted; category is a plain string here.
    parsed = ExtractedInventory.model_validate(
        {"items": [{"name": "Tent", "category": "weird", "confidence": 0.8}]}
    )
    assert parsed.items[0].category == "weird"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_community_schemas.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.schemas.community'`.

- [ ] **Step 3: Create the schema module**

Create `apps/backend/app/schemas/community.py`:

```python
"""Community-tier (Tier B) request/response schemas. Phase 1: inventory."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

ITEM_CATEGORIES = [
    "tools", "games", "books", "kitchen", "outdoor",
    "electronics", "furniture", "kids", "sports", "other",
]
_CATEGORY_PATTERN = "^(" + "|".join(ITEM_CATEGORIES) + ")$"

ITEM_CONDITIONS = ["new", "like_new", "good", "fair", "poor"]
_CONDITION_PATTERN = "^(" + "|".join(ITEM_CONDITIONS) + ")$"


class ItemCreate(BaseModel):
    """Manual item creation — category/condition are strictly validated."""

    name: str = Field(..., min_length=1, max_length=200)
    category: str = Field(default="other", pattern=_CATEGORY_PATTERN)
    tags: list[str] = Field(default_factory=list)
    quantity: int = Field(default=1, ge=1)
    condition: str | None = Field(default=None, pattern=_CONDITION_PATTERN)
    estimated_value_usd: float | None = Field(default=None, ge=0)
    location: str | None = Field(default=None, max_length=120)
    acquired_on: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ItemUpdate(BaseModel):
    """Partial update — every field optional; absent means "leave unchanged"."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, pattern=_CATEGORY_PATTERN)
    tags: list[str] | None = None
    quantity: int | None = Field(default=None, ge=1)
    condition: str | None = Field(default=None, pattern=_CONDITION_PATTERN)
    estimated_value_usd: float | None = Field(default=None, ge=0)
    location: str | None = Field(default=None, max_length=120)
    acquired_on: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ItemRead(BaseModel):
    """Persisted inventory item, returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: str
    tags: list[str]
    quantity: int
    condition: str | None
    estimated_value_usd: float | None
    location: str | None
    acquired_on: date | None
    photo_url: str | None
    source: str
    confidence: float | None
    notes: str | None
    created_at: datetime


class ExtractedInventoryItem(BaseModel):
    """One item the vision model extracted, pre-persistence.

    Permissive — parsed straight from untrusted LLM output, so `category` and
    `condition` are plain strings the service layer coerces to valid values.
    """

    name: str = Field(..., min_length=1, max_length=200)
    category: str = "other"
    tags: list[str] = Field(default_factory=list)
    quantity: int | None = Field(default=1, ge=1)
    condition: str | None = None
    estimated_value_usd: float | None = Field(default=None, ge=0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    notes: str | None = Field(default=None, max_length=500)


class ExtractedInventory(BaseModel):
    """Full structured response from extract_items_from_image."""

    items: list[ExtractedInventoryItem]


class ItemCaptureRequest(BaseModel):
    """Photo-to-inventory input. Image arrives as base64 (not persisted in v1)."""

    image_base64: str = Field(..., min_length=32, description="Base64-encoded image data")
    media_type: str = Field(
        default="image/jpeg", pattern=r"^image/(jpeg|jpg|png|webp|heic)$"
    )


class ItemCaptureResponse(BaseModel):
    items: list[ItemRead]
    created_count: int
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_community_schemas.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/schemas/community.py apps/backend/tests/test_community_schemas.py
git commit -m "feat(community): add Pydantic schemas for inventory items"
```

---

### Task 3: `extract_items_from_image` LLM function

**Files:**
- Modify: `apps/backend/app/services/llm.py`
- Test: `apps/backend/tests/test_community_llm.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_community_llm.py`:

```python
"""Tests for the inventory vision-extraction LLM function."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import llm


def _vision_response(items: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps({"items": items}))]
    )


def test_extract_items_from_image_parses_response(monkeypatch):
    fake = MagicMock()
    fake.messages.create.return_value = _vision_response(
        [
            {
                "name": "DeWalt 20V drill",
                "category": "tools",
                "tags": ["cordless", "power tool"],
                "quantity": 1,
                "condition": "good",
                "estimated_value_usd": 90,
                "confidence": 0.92,
                "notes": None,
            },
            {
                "name": "Catan",
                "category": "games",
                "tags": ["board game"],
                "quantity": 1,
                "condition": None,
                "estimated_value_usd": 35,
                "confidence": 0.97,
                "notes": None,
            },
        ]
    )
    monkeypatch.setattr(llm, "get_client", lambda: fake)

    result = llm.extract_items_from_image("x" * 64, "image/jpeg")

    assert len(result.items) == 2
    assert result.items[0].name == "DeWalt 20V drill"
    assert result.items[0].category == "tools"
    assert result.items[1].name == "Catan"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_community_llm.py -v`
Expected: FAIL with `AttributeError: module 'app.services.llm' has no attribute 'extract_items_from_image'`.

- [ ] **Step 3: Add the import**

In `apps/backend/app/services/llm.py`, add this line to the imports block, immediately after `from app.schemas.ai import ChatTurnResult`:

```python
from app.schemas.community import ExtractedInventory
```

- [ ] **Step 4: Add the function and its prompt**

In `apps/backend/app/services/llm.py`, immediately after the `extract_pantry_from_image` function (i.e. before the `# ---------- Stubs awaiting later sprints ----------` comment), add:

```python
# v0.1 — initial inventory-extraction prompt
INVENTORY_EXTRACT_SYSTEM = """You are a household inventory assistant. The user will send a photo \
of durable household possessions (a shelf of board games, a tool pegboard, a bookcase, sports \
gear). Identify every distinct item and return a structured inventory.

Rules:
- One entry per distinct item. If you see 8 identical folding chairs, return one entry with \
quantity=8.
- Use the most specific name you can read ("DeWalt 20V drill" beats "drill"; "Catan" beats \
"board game").
- category MUST be exactly one of: tools, games, books, kitchen, outdoor, electronics, \
furniture, kids, sports, other. Pick the closest fit; use "other" only when nothing fits.
- tags: 1-4 short lowercase keywords for finer search (e.g. "cordless", "board game", "6 players").
- condition: one of new, like_new, good, fair, poor — your best visual estimate, or null if unclear.
- estimated_value_usd: rough US replacement cost, or null if you cannot estimate.
- confidence: your subjective certainty 0..1 that the item exists as described.
- Do NOT include food, packaging, or background objects.

Respond ONLY with valid JSON conforming to this schema; no preamble, no code fences:
{
  "items": [
    {
      "name": "string",
      "category": "string",
      "tags": ["string", ...],
      "quantity": number,
      "condition": "string | null",
      "estimated_value_usd": number | null,
      "confidence": number,
      "notes": "string | null"
    }
  ]
}"""


def extract_items_from_image(
    image_base64: str, media_type: str = "image/jpeg"
) -> ExtractedInventory:
    """Photo → structured inventory items. Sonnet 4.6 vision + Pydantic validation."""
    response = get_client().messages.create(
        model=MODEL_VISION,
        max_tokens=2048,
        system=INVENTORY_EXTRACT_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_base64,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Extract every durable household item visible in this photo.",
                    },
                ],
            }
        ],
    )

    text_parts = [
        block.text for block in response.content if getattr(block, "type", None) == "text"
    ]
    if not text_parts:
        raise ValueError("LLM returned no text content")

    raw = _extract_json("".join(text_parts))
    return ExtractedInventory.model_validate(raw)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_community_llm.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/services/llm.py apps/backend/tests/test_community_llm.py
git commit -m "feat(community): add extract_items_from_image vision function"
```

---

### Task 4: Community items service

**Files:**
- Create: `apps/backend/app/services/community/__init__.py`
- Create: `apps/backend/app/services/community/items.py`
- Test: `apps/backend/tests/test_community_service.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_community_service.py`:

```python
"""Tests for the community inventory service layer."""
from __future__ import annotations

import uuid

import pytest

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.core import Event, Household, User
from app.services.community import items as items_service
from app.services.community.items import CommunityItemNotFound


def _ctx(db):
    return db.get(Household, DEV_HOUSEHOLD_ID), db.get(User, DEV_USER_ID)


def test_create_item_persists_and_emits_event(db):
    household, user = _ctx(db)
    item = items_service.create_item(
        db, household=household, user=user, name="Catan", category="games"
    )
    assert item.id is not None
    events = db.query(Event).filter_by(event_type="community.item.added").all()
    assert len(events) == 1
    assert events[0].entity_type == "item"
    assert events[0].entity_id == item.id


def test_create_item_coerces_unknown_category_to_other(db):
    household, user = _ctx(db)
    item = items_service.create_item(
        db, household=household, user=user, name="Mystery", category="spaceship"
    )
    assert item.category == "other"


def test_list_items_filters_by_category(db):
    household, user = _ctx(db)
    items_service.create_item(db, household=household, user=user, name="Drill", category="tools")
    items_service.create_item(db, household=household, user=user, name="Catan", category="games")
    tools = items_service.list_items(db, household=household, category="tools")
    assert [i.name for i in tools] == ["Drill"]


def test_update_item_changes_fields_and_emits_event(db):
    household, user = _ctx(db)
    item = items_service.create_item(db, household=household, user=user, name="Drill")
    items_service.update_item(
        db, household=household, user=user, item_id=item.id, location="garage"
    )
    assert item.location == "garage"
    events = db.query(Event).filter_by(event_type="community.item.updated").all()
    assert len(events) == 1


def test_soft_delete_item_sets_deleted_at_and_emits_event(db):
    household, user = _ctx(db)
    item = items_service.create_item(db, household=household, user=user, name="Drill")
    items_service.soft_delete_item(db, household=household, user=user, item_id=item.id)
    assert item.deleted_at is not None
    assert items_service.list_items(db, household=household) == []
    events = db.query(Event).filter_by(event_type="community.item.removed").all()
    assert len(events) == 1


def test_load_unknown_item_raises(db):
    household, user = _ctx(db)
    with pytest.raises(CommunityItemNotFound):
        items_service.update_item(
            db, household=household, user=user, item_id=uuid.uuid4(), name="x"
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_community_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.community'`.

- [ ] **Step 3: Create the package marker**

Create `apps/backend/app/services/community/__init__.py`:

```python
"""Community-tier (Tier B) service modules — Phase 1: inventory items."""
```

- [ ] **Step 4: Create the items service**

Create `apps/backend/app/services/community/items.py`:

```python
"""
Community inventory item helpers — Tier B Phase 1.

Create / update / soft-delete / list a household's inventory items, each
emitting the matching `community.item.*` event. Mirrors app/services/pantry.py.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.models.community import CommunityItem
from app.models.core import Household, User
from app.schemas.community import ITEM_CATEGORIES, ITEM_CONDITIONS
from app.services.events import emit_event


class CommunityItemNotFound(Exception):
    """Raised when an item id can't be resolved for the household."""


def _normalize_category(category: str | None) -> str:
    if category and category.strip().lower() in ITEM_CATEGORIES:
        return category.strip().lower()
    return "other"


def _normalize_condition(condition: str | None) -> str | None:
    if condition and condition.strip().lower() in ITEM_CONDITIONS:
        return condition.strip().lower()
    return None


def _load_owned_item(
    db: Session, household: Household, item_id: uuid.UUID
) -> CommunityItem:
    item = db.get(CommunityItem, item_id)
    if item is None or item.household_id != household.id or item.deleted_at is not None:
        raise CommunityItemNotFound(str(item_id))
    return item


def list_items(
    db: Session, *, household: Household, category: str | None = None
) -> list[CommunityItem]:
    """List a household's non-deleted items, newest first; optional category filter."""
    query = db.query(CommunityItem).filter(
        CommunityItem.household_id == household.id,
        CommunityItem.deleted_at.is_(None),
    )
    if category is not None:
        query = query.filter(CommunityItem.category == _normalize_category(category))
    return query.order_by(CommunityItem.created_at.desc()).all()


def create_item(
    db: Session,
    *,
    household: Household,
    user: User,
    name: str,
    category: str = "other",
    tags: list[str] | None = None,
    quantity: int | None = 1,
    condition: str | None = None,
    estimated_value_usd: float | None = None,
    location: str | None = None,
    acquired_on: date | None = None,
    notes: str | None = None,
    source: str = "manual",
    confidence: float | None = None,
    photo_url: str | None = None,
) -> CommunityItem:
    """Create an inventory item and emit community.item.added."""
    item = CommunityItem(
        household_id=household.id,
        created_by_user_id=user.id,
        name=name,
        category=_normalize_category(category),
        tags=tags or [],
        quantity=quantity if quantity is not None else 1,
        condition=_normalize_condition(condition),
        estimated_value_usd=estimated_value_usd,
        location=location,
        acquired_on=acquired_on,
        notes=notes,
        source=source,
        confidence=confidence,
        photo_url=photo_url,
    )
    db.add(item)
    db.flush()

    emit_event(
        db,
        event_type="community.item.added",
        household_id=household.id,
        user_id=user.id,
        entity_type="item",
        entity_id=item.id,
        payload={
            "name": item.name,
            "category": item.category,
            "quantity": item.quantity,
            "source": source,
        },
    )
    return item


def update_item(
    db: Session,
    *,
    household: Household,
    user: User,
    item_id: uuid.UUID,
    name: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    quantity: int | None = None,
    condition: str | None = None,
    estimated_value_usd: float | None = None,
    location: str | None = None,
    acquired_on: date | None = None,
    notes: str | None = None,
) -> CommunityItem:
    """Update supplied fields of an item; emit community.item.updated."""
    item = _load_owned_item(db, household, item_id)
    changed: dict[str, object] = {}
    if name is not None:
        item.name = name
        changed["name"] = name
    if category is not None:
        item.category = _normalize_category(category)
        changed["category"] = item.category
    if tags is not None:
        item.tags = tags
        changed["tags"] = tags
    if quantity is not None:
        item.quantity = quantity
        changed["quantity"] = quantity
    if condition is not None:
        item.condition = _normalize_condition(condition)
        changed["condition"] = item.condition
    if estimated_value_usd is not None:
        item.estimated_value_usd = estimated_value_usd
        changed["estimated_value_usd"] = estimated_value_usd
    if location is not None:
        item.location = location
        changed["location"] = location
    if acquired_on is not None:
        item.acquired_on = acquired_on
        changed["acquired_on"] = acquired_on.isoformat()
    if notes is not None:
        item.notes = notes
        changed["notes"] = notes
    if not changed:
        return item  # no-op update — don't emit a spurious event
    db.flush()

    emit_event(
        db,
        event_type="community.item.updated",
        household_id=household.id,
        user_id=user.id,
        entity_type="item",
        entity_id=item.id,
        payload={"name": item.name, "changed": changed},
    )
    return item


def soft_delete_item(
    db: Session, *, household: Household, user: User, item_id: uuid.UUID
) -> CommunityItem:
    """Soft-delete an item (sets deleted_at); emit community.item.removed."""
    item = _load_owned_item(db, household, item_id)
    item.deleted_at = datetime.now(UTC)
    db.flush()

    emit_event(
        db,
        event_type="community.item.removed",
        household_id=household.id,
        user_id=user.id,
        entity_type="item",
        entity_id=item.id,
        payload={"name": item.name},
    )
    return item
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_community_service.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/services/community/ apps/backend/tests/test_community_service.py
git commit -m "feat(community): add inventory items service layer"
```

---

### Task 5: Community router + mount

**Files:**
- Create: `apps/backend/app/routers/community.py`
- Modify: `apps/backend/app/main.py`
- Test: `apps/backend/tests/test_community_endpoints.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_community_endpoints.py`:

```python
"""End-to-end tests for the community inventory endpoints."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.auth import DEV_HOUSEHOLD_ID
from app.db import SessionLocal
from app.main import app
from app.models.core import Event
from app.services import llm


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_vision(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    return fake


def _vision_response(items: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps({"items": items}))]
    )


def test_create_and_list_item(client):
    resp = client.post(
        "/api/v1/community/items",
        json={"name": "Catan", "category": "games"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Catan"

    listed = client.get("/api/v1/community/items")
    assert listed.status_code == 200
    assert [i["name"] for i in listed.json()] == ["Catan"]


def test_list_filters_by_category(client):
    client.post("/api/v1/community/items", json={"name": "Drill", "category": "tools"})
    client.post("/api/v1/community/items", json={"name": "Catan", "category": "games"})
    resp = client.get("/api/v1/community/items?category=tools")
    assert [i["name"] for i in resp.json()] == ["Drill"]


def test_create_rejects_unknown_category(client):
    resp = client.post(
        "/api/v1/community/items", json={"name": "x", "category": "vehicles"}
    )
    assert resp.status_code == 422


def test_capture_creates_items_and_emits_events(client, mock_vision):
    mock_vision.messages.create.return_value = _vision_response(
        [
            {
                "name": "DeWalt drill",
                "category": "tools",
                "tags": ["cordless"],
                "quantity": 1,
                "condition": "good",
                "estimated_value_usd": 90,
                "confidence": 0.9,
                "notes": None,
            },
            {
                "name": "Catan",
                "category": "games",
                "tags": ["board game"],
                "quantity": 1,
                "condition": None,
                "estimated_value_usd": 35,
                "confidence": 0.95,
                "notes": None,
            },
        ]
    )
    resp = client.post(
        "/api/v1/community/items/capture",
        json={"image_base64": "x" * 64, "media_type": "image/jpeg"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created_count"] == 2

    with SessionLocal() as db:
        events = (
            db.query(Event)
            .filter(
                Event.event_type == "community.item.added",
                Event.household_id == DEV_HOUSEHOLD_ID,
            )
            .all()
        )
        assert len(events) == 2
        assert all(e.entity_type == "item" for e in events)


def test_update_item(client):
    created = client.post(
        "/api/v1/community/items", json={"name": "Drill", "category": "tools"}
    ).json()
    resp = client.patch(
        f"/api/v1/community/items/{created['id']}", json={"location": "garage"}
    )
    assert resp.status_code == 200
    assert resp.json()["location"] == "garage"


def test_update_unknown_item_returns_404(client):
    resp = client.patch(
        "/api/v1/community/items/00000000-0000-0000-0000-0000000000ff",
        json={"location": "garage"},
    )
    assert resp.status_code == 404


def test_delete_item(client):
    created = client.post(
        "/api/v1/community/items", json={"name": "Drill"}
    ).json()
    resp = client.delete(f"/api/v1/community/items/{created['id']}")
    assert resp.status_code == 200
    assert client.get("/api/v1/community/items").json() == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_community_endpoints.py -v`
Expected: FAIL — all requests return 404 (the router is not mounted yet).

- [ ] **Step 3: Create the router**

Create `apps/backend/app/routers/community.py`:

```python
"""Tier B — community routes. Phase 1: household inventory."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import CurrentHousehold, CurrentUser
from app.db import get_db
from app.models.community import CommunityItem
from app.schemas.community import (
    ItemCaptureRequest,
    ItemCaptureResponse,
    ItemCreate,
    ItemRead,
    ItemUpdate,
)
from app.services.community import items as items_service
from app.services.community.items import CommunityItemNotFound
from app.services.llm import extract_items_from_image

router = APIRouter()


@router.get("/items", response_model=list[ItemRead])
def list_items(
    household: CurrentHousehold,
    db: Annotated[Session, Depends(get_db)],
    category: Annotated[str | None, Query()] = None,
) -> list[CommunityItem]:
    """List the current household's inventory, newest first."""
    return items_service.list_items(db, household=household, category=category)


@router.post("/items", response_model=ItemRead)
def create_item(
    request: ItemCreate,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ItemRead:
    """Manually create one inventory item."""
    item = items_service.create_item(
        db,
        household=household,
        user=user,
        name=request.name,
        category=request.category,
        tags=request.tags,
        quantity=request.quantity,
        condition=request.condition,
        estimated_value_usd=request.estimated_value_usd,
        location=request.location,
        acquired_on=request.acquired_on,
        notes=request.notes,
        source="manual",
    )
    db.commit()
    db.refresh(item)
    return ItemRead.model_validate(item)


@router.post("/items/capture", response_model=ItemCaptureResponse)
def capture_items(
    request: ItemCaptureRequest,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ItemCaptureResponse:
    """Photo → inventory items. Sonnet 4.6 vision extracts; we persist + emit events."""
    extracted = extract_items_from_image(request.image_base64, request.media_type)

    created: list[CommunityItem] = []
    for ext in extracted.items:
        item = items_service.create_item(
            db,
            household=household,
            user=user,
            name=ext.name,
            category=ext.category,
            tags=ext.tags,
            quantity=ext.quantity or 1,
            condition=ext.condition,
            estimated_value_usd=ext.estimated_value_usd,
            notes=ext.notes,
            source="photo_capture",
            confidence=ext.confidence,
        )
        created.append(item)

    db.commit()
    for item in created:
        db.refresh(item)

    return ItemCaptureResponse(
        items=[ItemRead.model_validate(item) for item in created],
        created_count=len(created),
    )


@router.patch("/items/{item_id}", response_model=ItemRead)
def update_item(
    item_id: uuid.UUID,
    request: ItemUpdate,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ItemRead:
    """Update an inventory item's fields."""
    try:
        item = items_service.update_item(
            db,
            household=household,
            user=user,
            item_id=item_id,
            name=request.name,
            category=request.category,
            tags=request.tags,
            quantity=request.quantity,
            condition=request.condition,
            estimated_value_usd=request.estimated_value_usd,
            location=request.location,
            acquired_on=request.acquired_on,
            notes=request.notes,
        )
    except CommunityItemNotFound:
        raise HTTPException(404, "item not found") from None
    db.commit()
    db.refresh(item)
    return ItemRead.model_validate(item)


@router.delete("/items/{item_id}")
def delete_item(
    item_id: uuid.UUID,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    """Soft-delete an inventory item."""
    try:
        items_service.soft_delete_item(
            db, household=household, user=user, item_id=item_id
        )
    except CommunityItemNotFound:
        raise HTTPException(404, "item not found") from None
    db.commit()
    return {"status": "deleted", "id": str(item_id)}
```

- [ ] **Step 4: Mount the router**

In `apps/backend/app/main.py`, change the import line:

```python
from app.routers import ai, content, food, health, tracking
```

to:

```python
from app.routers import ai, community, content, food, health, tracking
```

Then replace these two lines:

```python
# Future tiers:
# app.include_router(bills.router, prefix="/api/v1/bills", tags=["bills"])
# app.include_router(community.router, prefix="/api/v1/community", tags=["community"])
```

with:

```python
# Tier B — community
app.include_router(community.router, prefix="/api/v1/community", tags=["community"])

# Future tiers:
# app.include_router(bills.router, prefix="/api/v1/bills", tags=["bills"])
```

Also update the `root()` handler's `modules` list from `["food", "content", "ai", "tracking"]` to `["food", "community", "content", "ai", "tracking"]`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_community_endpoints.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/routers/community.py apps/backend/app/main.py \
  apps/backend/tests/test_community_endpoints.py
git commit -m "feat(community): add inventory REST router at /api/v1/community"
```

---

### Task 6: Enable Tier B for the dev subscription

**Files:**
- Modify: `apps/backend/app/auth.py`
- Test: `apps/backend/tests/test_auth.py`

- [ ] **Step 1: Write the failing test**

Append this test to `apps/backend/tests/test_auth.py`:

```python
def test_dev_subscription_has_tier_b_enabled():
    from app.auth import DEV_USER_ID
    from app.db import SessionLocal
    from app.models.core import Subscription

    with SessionLocal() as db:
        sub = db.query(Subscription).filter_by(user_id=DEV_USER_ID).one()
        assert sub.tier_b_enabled is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_auth.py::test_dev_subscription_has_tier_b_enabled -v`
Expected: FAIL — `assert False is True` (the dev subscription was seeded with Tier B off).

- [ ] **Step 3: Update the seed**

In `apps/backend/app/auth.py`, inside `seed_dev_fixtures`, replace this block:

```python
        subscription = (
            db.query(Subscription).filter_by(user_id=DEV_USER_ID).one_or_none()
        )
        if subscription is None:
            db.add(
                Subscription(
                    user_id=DEV_USER_ID,
                    plan="suite",
                    status="active",
                    tier_a_enabled=True,
                )
            )
```

with:

```python
        subscription = (
            db.query(Subscription).filter_by(user_id=DEV_USER_ID).one_or_none()
        )
        if subscription is None:
            db.add(
                Subscription(
                    user_id=DEV_USER_ID,
                    plan="suite",
                    status="active",
                    tier_a_enabled=True,
                    tier_b_enabled=True,
                )
            )
        else:
            # Idempotently enable Tier B on pre-existing dev databases.
            subscription.tier_b_enabled = True
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_auth.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/auth.py apps/backend/tests/test_auth.py
git commit -m "feat(community): enable Tier B on the dev subscription"
```

---

### Task 7: `ChatAction` inventory types and fields

**Files:**
- Modify: `apps/backend/app/schemas/ai.py`
- Test: `apps/backend/tests/test_chat_schemas.py`

- [ ] **Step 1: Write the failing test**

Append this test to `apps/backend/tests/test_chat_schemas.py`:

```python
def test_chat_action_accepts_inventory_types_and_fields():
    from app.schemas.ai import ChatAction

    add = ChatAction(
        type="add_inventory_item",
        raw_name="DeWalt drill",
        category="tools",
        tags=["cordless"],
        condition="good",
        estimated_value_usd=90.0,
        location="garage",
    )
    assert add.type == "add_inventory_item"
    assert add.tags == ["cordless"]

    remove = ChatAction(
        type="remove_inventory_item",
        inventory_item_id="00000000-0000-0000-0000-000000000001",
    )
    assert remove.inventory_item_id is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_chat_schemas.py::test_chat_action_accepts_inventory_types_and_fields -v`
Expected: FAIL with a `ValidationError` — `add_inventory_item` is not an allowed `type`.

- [ ] **Step 3: Extend `ChatActionType`**

In `apps/backend/app/schemas/ai.py`, replace the `ChatActionType` definition:

```python
ChatActionType = Literal[
    "add_pantry_item",
    "remove_pantry_item",
    "update_pantry_item",
    "log_waste",
    "mark_recipe_cooked",
    "generate_meal_plan",
]
```

with:

```python
ChatActionType = Literal[
    "add_pantry_item",
    "remove_pantry_item",
    "update_pantry_item",
    "log_waste",
    "mark_recipe_cooked",
    "generate_meal_plan",
    "add_inventory_item",
    "update_inventory_item",
    "remove_inventory_item",
]
```

- [ ] **Step 4: Add the inventory fields to `ChatAction`**

In `apps/backend/app/schemas/ai.py`, inside the `ChatAction` class, add these fields immediately after the `dietary_constraints` field (the last field in the class):

```python
    # add / update / remove inventory item (Tier B). raw_name carries the item
    # name and quantity is reused from the pantry fields above.
    inventory_item_id: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    condition: str | None = None
    estimated_value_usd: float | None = None
    location: str | None = None
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_chat_schemas.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/schemas/ai.py apps/backend/tests/test_chat_schemas.py
git commit -m "feat(community): add inventory action types to ChatAction schema"
```

---

### Task 8: Chat service inventory wiring

**Files:**
- Modify: `apps/backend/app/services/chat.py`
- Test: `apps/backend/tests/test_community_chat.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_community_chat.py`:

```python
"""Tests for inventory wiring in the chat orchestration service."""
from __future__ import annotations

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.community import CommunityItem
from app.models.core import Household, User
from app.schemas.ai import ChatAction
from app.services import chat
from app.services.community import items as items_service


def _ctx(db):
    return db.get(Household, DEV_HOUSEHOLD_ID), db.get(User, DEV_USER_ID)


def test_normalize_page_maps_inventory_route():
    assert chat.normalize_page("/inventory") == "inventory"


def test_inventory_conversation_has_community_scope(db):
    household, _ = _ctx(db)
    conv = chat.get_or_create_conversation(db, household=household, page="/inventory")
    assert conv.scope == "community"


def test_pantry_conversation_keeps_food_scope(db):
    household, _ = _ctx(db)
    conv = chat.get_or_create_conversation(db, household=household, page="/pantry")
    assert conv.scope == "food"


def test_build_page_context_lists_inventory_ids(db):
    household, user = _ctx(db)
    item = items_service.create_item(
        db, household=household, user=user, name="Catan", category="games"
    )
    context = chat.build_page_context(db, household=household, page="inventory")
    assert str(item.id) in context
    assert "Catan" in context


def test_execute_action_add_inventory_item_creates_row(db):
    household, user = _ctx(db)
    action = ChatAction(type="add_inventory_item", raw_name="Tent", category="outdoor")
    result = chat._execute_action(db, household=household, user=user, action=action)
    assert result.status == "ok"
    rows = db.query(CommunityItem).filter_by(household_id=household.id).all()
    assert any(r.name == "Tent" for r in rows)


def test_execute_action_remove_inventory_bad_id_returns_error(db):
    household, user = _ctx(db)
    action = ChatAction(type="remove_inventory_item", inventory_item_id="not-a-uuid")
    result = chat._execute_action(db, household=household, user=user, action=action)
    assert result.status == "error"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_community_chat.py -v`
Expected: FAIL — `normalize_page("/inventory")` returns `"general"` and the inventory actions are unknown.

- [ ] **Step 3: Add imports to the chat service**

In `apps/backend/app/services/chat.py`, add these imports. After the line `from app.models.core import Household, User`:

```python
from app.models.community import CommunityItem
```

After the line `from app.services.events import emit_event`:

```python
from app.services.community import items as community_items
from app.services.community.items import CommunityItemNotFound
```

- [ ] **Step 4: Register the inventory page route**

In `apps/backend/app/services/chat.py`, add `"/inventory": "inventory",` to the `_ROUTE_TO_PAGE` dict, immediately after the `"/waste": "waste",` line:

```python
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
```

- [ ] **Step 5: Make `get_or_create_conversation` scope-aware**

In `apps/backend/app/services/chat.py`, add this helper immediately before the `get_or_create_conversation` function:

```python
def _scope_for_page(page_key: str) -> str:
    """The conversation scope for a page key: inventory is Tier B, the rest food."""
    return "community" if page_key == "inventory" else "food"
```

Then in `get_or_create_conversation`, change the `Conversation(...)` construction's `scope="food"` to `scope=_scope_for_page(key)`:

```python
    conv = Conversation(
        household_id=household.id,
        scope=_scope_for_page(key),
        surface="sidebar",
        title=key.capitalize(),
        metadata_={"page": key},
    )
```

- [ ] **Step 6: Add the inventory grounding context**

In `apps/backend/app/services/chat.py`, add this function immediately after `_savings_context`:

```python
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
```

- [ ] **Step 7: Branch `build_page_context` for the inventory page**

In `apps/backend/app/services/chat.py`, replace the body of `build_page_context`:

```python
def build_page_context(db: Session, *, household: Household, page: str) -> str:
    """Assemble the grounding block fed to Claude for a page. The pantry snapshot
    is included everywhere; plan/savings are layered on for the relevant pages."""
    key = normalize_page(page)
    sections = [_pantry_context(db, household)]
    if key in ("plan", "shopping"):
        sections.append(_plan_context(db, household))
    if key in ("home", "waste", "general"):
        sections.append(_savings_context(db, household))
    return "\n\n".join(s for s in sections if s)
```

with:

```python
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
```

- [ ] **Step 8: Add the inventory action handlers**

In `apps/backend/app/services/chat.py`, add these three handlers immediately after `_do_generate_meal_plan` (i.e. before the `_DISPATCH` dict):

```python
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
```

- [ ] **Step 9: Register the handlers in `_DISPATCH`**

In `apps/backend/app/services/chat.py`, replace the `_DISPATCH` dict:

```python
_DISPATCH = {
    "add_pantry_item": _do_add_pantry_item,
    "remove_pantry_item": _do_remove_pantry_item,
    "update_pantry_item": _do_update_pantry_item,
    "log_waste": _do_log_waste,
    "mark_recipe_cooked": _do_mark_recipe_cooked,
    "generate_meal_plan": _do_generate_meal_plan,
}
```

with:

```python
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
```

- [ ] **Step 10: Run the test to verify it passes**

Run: `uv run pytest tests/test_community_chat.py tests/test_chat_service.py -v`
Expected: PASS (the new file plus the unchanged food chat tests still pass).

- [ ] **Step 11: Commit**

```bash
git add apps/backend/app/services/chat.py apps/backend/tests/test_community_chat.py
git commit -m "feat(community): wire inventory into the chat assistant"
```

---

### Task 9: Extend the chat LLM prompt with inventory actions

**Files:**
- Modify: `apps/backend/app/services/llm.py`
- Test: `apps/backend/tests/test_chat_llm.py`

- [ ] **Step 1: Write the failing test**

Append this test to `apps/backend/tests/test_chat_llm.py`:

```python
def test_chat_system_prompt_describes_inventory_actions():
    from app.services.llm import CHAT_SYSTEM

    assert "add_inventory_item" in CHAT_SYSTEM
    assert "update_inventory_item" in CHAT_SYSTEM
    assert "remove_inventory_item" in CHAT_SYSTEM
    # The page-scoping rule keeps food vs. inventory actions separate.
    assert "inventory" in CHAT_SYSTEM.lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_chat_llm.py::test_chat_system_prompt_describes_inventory_actions -v`
Expected: FAIL — `assert "add_inventory_item" in CHAT_SYSTEM` is False.

- [ ] **Step 3: Extend the `CHAT_SYSTEM` prompt**

In `apps/backend/app/services/llm.py`, change the prompt version comment above `CHAT_SYSTEM` from:

```python
# v0.1 — initial chat prompt
```

to:

```python
# v0.2 — adds Tier B inventory actions
```

Then, inside the `CHAT_SYSTEM` string, locate the `generate_meal_plan` action description block:

```
- generate_meal_plan: generate a new weekly dinner plan.
    fields: week_start (YYYY-MM-DD, optional), target_budget_usd (optional number),
    dinners_per_week (1-7, optional), dietary_constraints (list of strings, optional)
```

and insert the following immediately after it (before the blank line and the `Rules:` line):

```
- add_inventory_item: add a durable item (game, tool, book, gear) to the household inventory.
    fields: raw_name (required), category (optional: tools | games | books | kitchen | outdoor |
    electronics | furniture | kids | sports | other), tags (list of strings, optional),
    quantity (number, optional), condition (optional: new | like_new | good | fair | poor),
    estimated_value_usd (optional number), location (optional string)
- update_inventory_item: change an inventory item's fields.
    fields: inventory_item_id (required - MUST be an id from CONTEXT), raw_name / category /
    tags / quantity / condition / estimated_value_usd / location (optional)
- remove_inventory_item: remove an inventory item.
    fields: inventory_item_id (required - MUST be an id from the CONTEXT block)
```

Then add this bullet to the existing `Rules:` section, immediately after the line that begins `- When the user asks to add multiple items`:

```
- The pantry, recipe, and meal-plan actions apply ONLY to food pages. The inventory \
actions apply ONLY to the "inventory" page. Use the CURRENT PAGE marker to decide \
which set of actions is valid, and never mix them.
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_chat_llm.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/services/llm.py apps/backend/tests/test_chat_llm.py
git commit -m "feat(community): describe inventory actions in the chat prompt (v0.2)"
```

---

### Task 10: Frontend types and API client

**Files:**
- Modify: `apps/web/src/lib/types.ts`
- Modify: `apps/web/src/lib/api.ts`

- [ ] **Step 1: Add the inventory types**

In `apps/web/src/lib/types.ts`, append at the end of the file:

```typescript
// ---------- Community / inventory (Tier B) ----------

export type ItemCategory =
  | "tools"
  | "games"
  | "books"
  | "kitchen"
  | "outdoor"
  | "electronics"
  | "furniture"
  | "kids"
  | "sports"
  | "other";

export type ItemCondition = "new" | "like_new" | "good" | "fair" | "poor";

export interface InventoryItem {
  id: string;
  name: string;
  category: ItemCategory;
  tags: string[];
  quantity: number;
  condition: ItemCondition | null;
  estimated_value_usd: number | null;
  location: string | null;
  photo_url: string | null;
  source: string;
  confidence: number | null;
  notes: string | null;
  created_at: string;
}

export interface ItemCaptureResponse {
  items: InventoryItem[];
  created_count: number;
}
```

- [ ] **Step 2: Add the API client functions**

In `apps/web/src/lib/api.ts`, add `InventoryItem`, `ItemCaptureResponse`, and `ItemCategory` to the type import block at the top (keep the list alphabetically sorted — insert `ContentItem`-adjacent and `Streak`-adjacent as appropriate):

```typescript
  InventoryItem,
  ItemCaptureResponse,
  ItemCategory,
```

Then append these functions at the end of `apps/web/src/lib/api.ts`:

```typescript
// ---------- Community / inventory (Tier B) ----------

export function listInventory(category?: string): Promise<InventoryItem[]> {
  const qs = category ? `?category=${encodeURIComponent(category)}` : "";
  return api<InventoryItem[]>(`/api/v1/community/items${qs}`);
}

export function captureInventory(
  imageBase64: string,
  mediaType: string,
): Promise<ItemCaptureResponse> {
  return api<ItemCaptureResponse>("/api/v1/community/items/capture", {
    method: "POST",
    body: JSON.stringify({ image_base64: imageBase64, media_type: mediaType }),
  });
}

export function createInventoryItem(args: {
  name: string;
  category?: ItemCategory;
  tags?: string[];
  quantity?: number;
  location?: string;
  notes?: string;
}): Promise<InventoryItem> {
  return api<InventoryItem>("/api/v1/community/items", {
    method: "POST",
    body: JSON.stringify({
      name: args.name,
      category: args.category ?? "other",
      tags: args.tags ?? [],
      quantity: args.quantity ?? 1,
      location: args.location,
      notes: args.notes,
    }),
  });
}

export function deleteInventoryItem(id: string): Promise<{ status: string }> {
  return api<{ status: string }>(`/api/v1/community/items/${id}`, {
    method: "DELETE",
  });
}
```

- [ ] **Step 3: Verify the frontend typechecks**

Run: `cd apps/web && pnpm typecheck`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/lib/types.ts apps/web/src/lib/api.ts
git commit -m "feat(community): add inventory types and API client functions"
```

---

### Task 11: Frontend `/inventory` page

**Files:**
- Create: `apps/web/src/app/inventory/page.tsx`

- [ ] **Step 1: Create the page**

Create `apps/web/src/app/inventory/page.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import {
  captureInventory,
  createInventoryItem,
  deleteInventoryItem,
  fileToBase64,
  listInventory,
} from "@/lib/api";
import type { InventoryItem, ItemCategory } from "@/lib/types";

const CATEGORIES: ItemCategory[] = [
  "tools",
  "games",
  "books",
  "kitchen",
  "outdoor",
  "electronics",
  "furniture",
  "kids",
  "sports",
  "other",
];

type Status =
  | { kind: "idle" }
  | { kind: "uploading" }
  | { kind: "error"; message: string }
  | { kind: "success"; created: number };

export default function InventoryPage() {
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [filter, setFilter] = useState<ItemCategory | "all">("all");
  const [newName, setNewName] = useState("");
  const [newCategory, setNewCategory] = useState<ItemCategory>("other");

  async function refresh() {
    try {
      const data = await listInventory(filter === "all" ? undefined : filter);
      setItems(data);
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  async function handleFile(file: File) {
    setStatus({ kind: "uploading" });
    try {
      const { base64, mediaType } = await fileToBase64(file);
      const resp = await captureInventory(base64, mediaType);
      setStatus({ kind: "success", created: resp.created_count });
      await refresh();
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  }

  async function handleAdd() {
    const name = newName.trim();
    if (!name) return;
    try {
      await createInventoryItem({ name, category: newCategory });
      setNewName("");
      setNewCategory("other");
      await refresh();
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteInventoryItem(id);
      await refresh();
    } catch (err) {
      setStatus({ kind: "error", message: (err as Error).message });
    }
  }

  const isUploading = status.kind === "uploading";

  return (
    <div className="min-h-screen px-6 py-10 md:px-12 max-w-4xl mx-auto">
      <header className="mb-10">
        <h1 className="text-3xl font-bold text-ink">Inventory</h1>
        <p className="mt-1 text-stone-600">
          Catalog what your household owns — games, tools, books, gear.
        </p>
      </header>

      <section className="mb-8">
        <label
          htmlFor="inventory-photo"
          className={`flex flex-col items-center justify-center gap-2 cursor-pointer rounded-xl border-2 border-dashed p-10 transition ${
            isUploading
              ? "border-amber-400 bg-amber-50"
              : "border-stone-300 bg-white hover:border-amber-400"
          }`}
        >
          <span className="text-4xl">📦</span>
          <span className="text-stone-700 font-medium">
            {isUploading ? "Reading photo with Claude…" : "Tap to capture or upload"}
          </span>
          <span className="text-xs text-stone-500">
            A shelf of games, a tool pegboard, a bookcase
          </span>
          <input
            id="inventory-photo"
            type="file"
            accept="image/*"
            capture="environment"
            className="hidden"
            disabled={isUploading}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleFile(file);
              e.target.value = "";
            }}
          />
        </label>

        {status.kind === "error" && (
          <div className="mt-4 rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-800">
            {status.message}
          </div>
        )}
        {status.kind === "success" && (
          <div className="mt-4 rounded-md bg-emerald-50 border border-emerald-200 px-4 py-3 text-sm text-emerald-800">
            Added {status.created} {status.created === 1 ? "item" : "items"} to your
            inventory.
          </div>
        )}
      </section>

      <section className="mb-10 flex flex-wrap items-end gap-3">
        <div className="flex flex-col">
          <label htmlFor="new-name" className="text-xs text-stone-500 mb-1">
            Item name
          </label>
          <input
            id="new-name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="DeWalt 20V drill"
            className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
          />
        </div>
        <div className="flex flex-col">
          <label htmlFor="new-category" className="text-xs text-stone-500 mb-1">
            Category
          </label>
          <select
            id="new-category"
            value={newCategory}
            onChange={(e) => setNewCategory(e.target.value as ItemCategory)}
            className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
          >
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
        <button
          onClick={handleAdd}
          disabled={!newName.trim()}
          className="rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-paper transition hover:bg-clay disabled:opacity-50"
        >
          Add item
        </button>
      </section>

      <section>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-xl font-semibold text-stone-900">
            Your inventory ({items.length})
          </h2>
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value as ItemCategory | "all")}
            className="rounded-lg border border-stone-300 bg-white px-3 py-1.5 text-sm"
          >
            <option value="all">All categories</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
        {items.length === 0 ? (
          <p className="text-stone-500 text-sm">
            Nothing yet. Capture a photo or add an item to start.
          </p>
        ) : (
          <ul className="divide-y divide-stone-200 rounded-lg border border-stone-200 bg-white">
            {items.map((item) => (
              <li
                key={item.id}
                className="flex items-center justify-between px-4 py-3"
              >
                <div>
                  <div className="font-medium text-stone-900">
                    {item.name}
                    {item.quantity > 1 && (
                      <span className="text-stone-500"> ×{item.quantity}</span>
                    )}
                  </div>
                  <div className="text-xs text-stone-500 mt-0.5">
                    {item.category}
                    {item.condition && ` · ${item.condition.replace("_", " ")}`}
                    {item.location && ` · ${item.location}`}
                    {item.tags.length > 0 && ` · ${item.tags.join(", ")}`}
                  </div>
                </div>
                <button
                  onClick={() => handleDelete(item.id)}
                  className="text-xs text-stone-400 hover:text-red-600 transition"
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
```

- [ ] **Step 2: Verify the frontend typechecks**

Run: `cd apps/web && pnpm typecheck`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/app/inventory/page.tsx
git commit -m "feat(community): add the /inventory page"
```

---

### Task 12: Frontend sidebar navigation link

**Files:**
- Modify: `apps/web/src/components/Sidebar.tsx`

- [ ] **Step 1: Add the Household section**

In `apps/web/src/components/Sidebar.tsx`, in the `SECTIONS` array, add a new section between the `Kitchen` section and the `Library` section:

```typescript
  {
    title: "Household",
    items: [{ href: "/inventory", label: "Inventory" }],
  },
```

The `SECTIONS` array should then read:

```typescript
const SECTIONS: NavSection[] = [
  {
    title: "Overview",
    items: [{ href: "/", label: "Today" }],
  },
  {
    title: "Kitchen",
    items: [
      { href: "/pantry", label: "Pantry" },
      { href: "/stretch", label: "Recipe stretcher" },
      { href: "/plan", label: "Meal plan" },
      { href: "/shopping", label: "Shopping list" },
      { href: "/preservation", label: "Preservation" },
      { href: "/waste", label: "Waste & savings" },
    ],
  },
  {
    title: "Household",
    items: [{ href: "/inventory", label: "Inventory" }],
  },
  {
    title: "Library",
    items: [{ href: "/watch", label: "Watch" }],
  },
];
```

- [ ] **Step 2: Verify the frontend typechecks**

Run: `cd apps/web && pnpm typecheck`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/Sidebar.tsx
git commit -m "feat(community): add Inventory to the sidebar navigation"
```

---

### Task 13: Full verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full backend test suite**

Run: `cd apps/backend && uv run pytest`
Expected: PASS — all tests, including the pre-existing 134, plus the new community tests.

- [ ] **Step 2: Run the backend linter and type checker**

Run: `cd apps/backend && uv run ruff check . && uv run mypy app`
Expected: no errors. If `ruff` reports formatting issues, run `uv run ruff format .` and re-run, then amend the relevant commit or add a `chore` commit.

- [ ] **Step 3: Verify the migration round-trips**

Run: `cd apps/backend && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: downgrade drops `community.items` and the `community` schema; upgrade recreates them. No errors.

- [ ] **Step 4: Run the frontend type check and build**

Run: `cd apps/web && pnpm typecheck && pnpm build`
Expected: typecheck passes; build succeeds.

- [ ] **Step 5: Smoke-test the running app (optional but recommended)**

Run `./frugal up`, open `http://localhost:3000/inventory`, add an item manually, confirm it appears, open the Hearth chat on that page and ask "what's in my inventory?" — confirm a grounded answer. Then `./frugal down`.

- [ ] **Step 6: Commit any lint/format fixes**

```bash
git add -A
git commit -m "chore(community): apply lint and format fixes"
```

(Skip this commit if Steps 1–4 produced no changes.)

---

## Self-Review

**Spec coverage** — every section of `2026-05-21-phase-1-household-inventory-design.md` maps to a task:
- §3 data model → Task 1. §4 LLM → Task 3. §5 API → Task 5. §6 events → emitted by the service in Task 4. §7 schemas → Task 2; service package → Task 4; migration → Task 1; subscription gating → Task 6; frontend → Tasks 10–12. §8 chat parity → Tasks 7 (schema), 8 (service), 9 (prompt). §10 tests → co-located in each task plus Task 13.

**Placeholder scan** — no TBDs; every code step shows complete content; every command states expected output.

**Type consistency** — `CommunityItem` (model), `ItemCreate`/`ItemUpdate`/`ItemRead`/`ExtractedInventory`/`ExtractedInventoryItem`/`ItemCaptureRequest`/`ItemCaptureResponse` (schemas), `community_items.{create_item,update_item,soft_delete_item,list_items}` and `CommunityItemNotFound` (service) are used with identical names across the router (Task 5) and chat service (Task 8). Event types `community.item.{added,updated,removed}` match between the service (Task 4) and tests. Frontend `InventoryItem` / `ItemCategory` / `ItemCaptureResponse` match between `types.ts`, `api.ts`, and the page.
