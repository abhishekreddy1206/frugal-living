# Pantry-Aware Recipe Suggestions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `/watch` video library surface saved cooking videos ranked by how well their ingredients match the household's current pantry.

**Architecture:** Two stages. Enrichment runs once per video (YouTube Data API description → one Claude call extracts ingredients → resolved to canonical `food.ingredients` IDs, stored on the `ContentItem`). Ranking is rule-based ID-overlap against the live pantry, computed per request, never persisted.

**Tech Stack:** FastAPI / SQLAlchemy 2.0 / PostgreSQL backend, Next.js 14 / TypeScript frontend, Claude via the Claude Code CLI, YouTube Data API v3.

**Spec:** `docs/superpowers/specs/2026-05-21-pantry-video-suggestions-design.md`

---

## File structure

| File | Responsibility | Action |
|---|---|---|
| `apps/backend/app/schemas/content.py` | + chat/suggestion schemas | Modify |
| `apps/backend/app/services/youtube.py` | + Data API fetch + unified resolver | Modify |
| `apps/backend/app/services/llm.py` | + `extract_video_ingredients` | Modify |
| `apps/backend/app/services/content.py` | enrichment + pantry-fit ranking + backfill | Create |
| `apps/backend/app/routers/content.py` | capture rewrite + 2 new endpoints | Modify |
| `apps/web/src/lib/types.ts`, `api.ts` | + suggestion types + client fn | Modify |
| `apps/web/src/app/watch/page.tsx` | "Cook from your pantry" section | Modify |
| `apps/backend/tests/test_*.py` | unit + endpoint tests | Create/Modify |
| `docs/architecture.md`, `CLAUDE.md` | new event type + status | Modify |

Backend commands run from `apps/backend/` (`uv run ...`); frontend from `apps/web/` (`pnpm ...`).

---

## Task 1: Content schemas

**Files:**
- Modify: `apps/backend/app/schemas/content.py`
- Test: `apps/backend/tests/test_content_schemas.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_content_schemas.py`:

```python
"""Tests for the recipe-suggestion content schemas."""
from __future__ import annotations

from app.schemas.content import RecipeSuggestion, VideoIngredients


def test_video_ingredients_parses_llm_shape():
    parsed = VideoIngredients.model_validate(
        {"is_recipe_video": True, "dish_name": "Tomato Pasta", "ingredients": ["tomato", "pasta"]}
    )
    assert parsed.is_recipe_video is True
    assert parsed.ingredients == ["tomato", "pasta"]


def test_video_ingredients_defaults():
    parsed = VideoIngredients.model_validate({"is_recipe_video": False})
    assert parsed.dish_name is None
    assert parsed.ingredients == []


def test_recipe_suggestion_round_trips():
    import uuid

    s = RecipeSuggestion(
        id=uuid.uuid4(),
        provider="youtube",
        external_id="abc",
        title="t",
        url=None,
        author=None,
        thumbnail_url=None,
        duration_seconds=None,
        match_score=3.0,
        matched_ingredients=["tomato"],
        match_reason="Uses tomato",
    )
    assert s.match_score == 3.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_content_schemas.py -v`
Expected: FAIL — `ImportError: cannot import name 'RecipeSuggestion'`.

- [ ] **Step 3: Add the schemas**

Append to `apps/backend/app/schemas/content.py`:

```python
class VideoIngredients(BaseModel):
    """LLM output — ingredients extracted from a video's text."""

    is_recipe_video: bool
    dish_name: str | None = None
    ingredients: list[str] = Field(default_factory=list)


class RecipeSuggestion(BaseModel):
    """A saved video ranked by pantry fit. Built by keyword in the router."""

    id: uuid.UUID
    provider: str
    external_id: str
    title: str
    url: str | None
    author: str | None
    thumbnail_url: str | None
    duration_seconds: int | None
    match_score: float
    matched_ingredients: list[str]
    match_reason: str


class RecipeSuggestionsResponse(BaseModel):
    suggestions: list[RecipeSuggestion]
    pantry_size: int


class EnrichResponse(BaseModel):
    enriched: int
    failed: int
    remaining: int
```

(`uuid`, `BaseModel`, `Field` are already imported at the top of the file.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_content_schemas.py -v`
Expected: PASS — 3 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/schemas/content.py apps/backend/tests/test_content_schemas.py
git commit -m "feat(content): add recipe-suggestion schemas"
```

---

## Task 2: YouTube Data API fetch + unified resolver

**Files:**
- Modify: `apps/backend/app/services/youtube.py`
- Test: `apps/backend/tests/test_youtube.py`

- [ ] **Step 1: Write the failing test**

Append to `apps/backend/tests/test_youtube.py`:

```python
def _data_api_payload(*, description="", tags=None, duration="PT5M30S"):
    return {
        "items": [
            {
                "snippet": {
                    "title": "Frugal Tomato Pasta",
                    "channelTitle": "Test Channel",
                    "description": description,
                    "tags": tags or [],
                    "publishedAt": "2026-01-15T12:00:00Z",
                },
                "contentDetails": {"duration": duration},
            }
        ]
    }


def test_fetch_video_details_returns_none_without_key(monkeypatch):
    monkeypatch.setattr(youtube.settings, "youtube_api_key", "")
    assert youtube.fetch_video_details("dQw4w9WgXcQ") is None


def test_fetch_video_details_parses_payload(monkeypatch):
    monkeypatch.setattr(youtube.settings, "youtube_api_key", "test-key")
    monkeypatch.setattr(
        youtube.httpx,
        "get",
        lambda *a, **k: _FakeResponse(200, _data_api_payload(description="Uses tomato and pasta.")),
    )
    details = youtube.fetch_video_details("dQw4w9WgXcQ")
    assert details is not None
    assert details.description == "Uses tomato and pasta."
    assert details.duration_seconds == 330
    assert details.author == "Test Channel"


def test_fetch_video_details_returns_none_on_error(monkeypatch):
    monkeypatch.setattr(youtube.settings, "youtube_api_key", "test-key")
    monkeypatch.setattr(youtube.httpx, "get", lambda *a, **k: _FakeResponse(403, {}))
    assert youtube.fetch_video_details("dQw4w9WgXcQ") is None


def test_resolve_video_metadata_prefers_data_api(monkeypatch):
    monkeypatch.setattr(youtube.settings, "youtube_api_key", "test-key")
    monkeypatch.setattr(
        youtube.httpx,
        "get",
        lambda *a, **k: _FakeResponse(200, _data_api_payload(description="desc")),
    )
    meta = youtube.resolve_video_metadata(VIDEO_URL)
    assert meta.description == "desc"
    assert meta.video_id == "dQw4w9WgXcQ"


def test_resolve_video_metadata_falls_back_to_oembed(monkeypatch):
    monkeypatch.setattr(youtube.settings, "youtube_api_key", "")  # no key → no Data API

    def fake_oembed(url):
        return youtube.YouTubeMetadata(
            video_id="dQw4w9WgXcQ",
            url=url,
            title="oEmbed title",
            author="oEmbed author",
            thumbnail_url="https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        )

    monkeypatch.setattr(youtube, "fetch_youtube_metadata", fake_oembed)
    meta = youtube.resolve_video_metadata(VIDEO_URL)
    assert meta.title == "oEmbed title"
    assert meta.description is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_youtube.py -v`
Expected: FAIL — `AttributeError: module 'app.services.youtube' has no attribute 'fetch_video_details'`.

- [ ] **Step 3: Implement the Data API fetch + resolver**

In `apps/backend/app/services/youtube.py`, update the top imports. The current import block is:

```python
from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from app.config import settings
```

Replace it with:

```python
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from app.config import settings

logger = logging.getLogger(__name__)
```

Then add a Data API URL constant next to `_OEMBED_URL`:

```python
_DATA_API_URL = "https://www.googleapis.com/youtube/v3/videos"
_ISO8601_DURATION_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")
```

Then append to the end of `apps/backend/app/services/youtube.py` (before `run_ingestion`, or after — placement is not critical, but keep `run_ingestion` last):

```python
def _parse_iso8601_duration(value: str | None) -> int | None:
    """Convert a YouTube ISO-8601 duration ('PT5M30S') to total seconds."""
    if not value:
        return None
    match = _ISO8601_DURATION_RE.fullmatch(value)
    if match is None:
        return None
    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


@dataclass
class VideoDetails:
    """Rich video metadata from the YouTube Data API."""

    title: str
    author: str | None
    description: str
    youtube_tags: list[str]
    duration_seconds: int | None
    published_at: datetime | None


def fetch_video_details(video_id: str) -> VideoDetails | None:
    """Fetch rich metadata via the YouTube Data API. Returns None when no API key
    is configured, or the call fails, or the video isn't found — callers fall back."""
    if not settings.youtube_api_key:
        return None
    try:
        resp = httpx.get(
            _DATA_API_URL,
            params={
                "part": "snippet,contentDetails",
                "id": video_id,
                "key": settings.youtube_api_key,
            },
            timeout=10.0,
        )
    except httpx.HTTPError as e:
        logger.warning("YouTube Data API request failed for %s: %s", video_id, e)
        return None
    if resp.status_code != 200:
        logger.warning("YouTube Data API returned %s for %s", resp.status_code, video_id)
        return None
    try:
        data = resp.json()
    except ValueError:
        logger.warning("YouTube Data API returned an unreadable body for %s", video_id)
        return None
    items = data.get("items") if isinstance(data, dict) else None
    if not items:
        logger.warning("YouTube Data API found no video for %s", video_id)
        return None

    snippet = items[0].get("snippet") or {}
    content_details = items[0].get("contentDetails") or {}
    published_at: datetime | None = None
    published_raw = snippet.get("publishedAt")
    if published_raw:
        try:
            published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
        except ValueError:
            published_at = None

    return VideoDetails(
        title=snippet.get("title") or "Untitled video",
        author=snippet.get("channelTitle"),
        description=snippet.get("description") or "",
        youtube_tags=list(snippet.get("tags") or []),
        duration_seconds=_parse_iso8601_duration(content_details.get("duration")),
        published_at=published_at,
    )


@dataclass
class VideoMetadata:
    """Unified capture metadata. description/youtube_tags/duration/published_at are
    populated only when the Data API resolved the video; oEmbed fills the rest."""

    video_id: str
    url: str
    title: str
    author: str | None
    thumbnail_url: str
    description: str | None
    youtube_tags: list[str] = field(default_factory=list)
    duration_seconds: int | None = None
    published_at: datetime | None = None


def resolve_video_metadata(url: str) -> VideoMetadata:
    """Resolve a YouTube URL to capture metadata — Data API first (rich), oEmbed
    fallback (title/author/thumbnail only). Raises ValueError if neither resolves."""
    video_id = parse_video_id(url.strip())
    if video_id is None:
        raise ValueError("Not a recognizable YouTube video URL")
    canonical = f"https://www.youtube.com/watch?v={video_id}"
    thumbnail = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

    details = fetch_video_details(video_id)
    if details is not None:
        return VideoMetadata(
            video_id=video_id,
            url=canonical,
            title=details.title,
            author=details.author,
            thumbnail_url=thumbnail,
            description=details.description,
            youtube_tags=details.youtube_tags,
            duration_seconds=details.duration_seconds,
            published_at=details.published_at,
        )

    oembed = fetch_youtube_metadata(canonical)  # raises ValueError if this also fails
    return VideoMetadata(
        video_id=video_id,
        url=oembed.url,
        title=oembed.title,
        author=oembed.author,
        thumbnail_url=oembed.thumbnail_url,
        description=None,
    )
```

Leave `fetch_youtube_metadata`, `parse_video_id`, `YouTubeMetadata`, and `run_ingestion` unchanged.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_youtube.py -v`
Expected: PASS — the 2 pre-existing tests plus the 5 new ones.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/services/youtube.py apps/backend/tests/test_youtube.py
git commit -m "feat(content): add YouTube Data API fetch and unified metadata resolver"
```

---

## Task 3: `extract_video_ingredients` LLM function

**Files:**
- Modify: `apps/backend/app/services/llm.py`
- Test: `apps/backend/tests/test_video_ingredients.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_video_ingredients.py`:

```python
"""Tests for the extract_video_ingredients LLM function."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import llm


def _fake_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def test_extract_video_ingredients_parses_recipe(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    fake.messages.create.return_value = _fake_response(
        json.dumps(
            {
                "is_recipe_video": True,
                "dish_name": "Tomato Pasta",
                "ingredients": ["tomato", "pasta", "garlic"],
            }
        )
    )
    result = llm.extract_video_ingredients("Easy Tomato Pasta", "A quick weeknight dinner.", ["pasta"])
    assert result.is_recipe_video is True
    assert result.dish_name == "Tomato Pasta"
    assert "garlic" in result.ingredients


def test_extract_video_ingredients_handles_non_recipe(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    fake.messages.create.return_value = _fake_response(
        '```json\n{"is_recipe_video": false, "dish_name": null, "ingredients": []}\n```'
    )
    result = llm.extract_video_ingredients("My budgeting tips", "How I save money.", [])
    assert result.is_recipe_video is False
    assert result.ingredients == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_video_ingredients.py -v`
Expected: FAIL — `AttributeError: module 'app.services.llm' has no attribute 'extract_video_ingredients'`.

- [ ] **Step 3: Add the prompt and function to `llm.py`**

In `apps/backend/app/services/llm.py`, find the import line `from app.schemas.ai import ChatTurnResult` and add directly below it:

```python
from app.schemas.content import VideoIngredients
```

Then append to the end of `apps/backend/app/services/llm.py`:

```python
# ---------- Video ingredient extraction ----------

# v0.1 — initial video-ingredient extraction prompt
VIDEO_INGREDIENTS_SYSTEM = """You identify the food ingredients a cooking video uses.

You are given a YouTube video's title, the uploader's tags, and its description. Decide \
whether it is a cooking/recipe video, and if so, list the ingredients a cook would need.

Rules:
- is_recipe_video: true ONLY if the video teaches cooking a dish or recipe. False for \
non-cooking content (vlogs, hauls, budgeting/finance tips, product reviews, etc.).
- ingredients: common ingredient names (e.g. "chicken", "olive oil", "garlic"). Lowercase, \
singular where natural. Only ingredients actually used in the dish — never equipment, \
never serving suggestions. Empty list when is_recipe_video is false.
- dish_name: the name of the dish if clear, otherwise null.
- Do not invent ingredients the text does not support.

Respond ONLY with valid JSON conforming to this schema; no preamble, no code fences:
{ "is_recipe_video": boolean, "dish_name": "string | null", "ingredients": ["string", ...] }"""


def extract_video_ingredients(
    title: str, description: str, youtube_tags: list[str]
) -> VideoIngredients:
    """Extract a video's ingredient list + recipe-video classification from its text."""
    tags_line = ", ".join(youtube_tags) if youtube_tags else "(none)"
    user_message = (
        f"Title: {title}\n\n"
        f"Uploader tags: {tags_line}\n\n"
        f"Description:\n{description or '(no description)'}"
    )
    response = get_client().messages.create(
        model=MODEL_FAST,
        max_tokens=1024,
        system=VIDEO_INGREDIENTS_SYSTEM,
        messages=[{"role": "user", "content": user_message}],
    )
    text_parts = [
        block.text for block in response.content if getattr(block, "type", None) == "text"
    ]
    if not text_parts:
        raise ValueError("LLM returned no text content")
    raw = _extract_json("".join(text_parts))
    return VideoIngredients.model_validate(raw)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_video_ingredients.py -v`
Expected: PASS — 2 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/services/llm.py apps/backend/tests/test_video_ingredients.py
git commit -m "feat(content): add extract_video_ingredients LLM function"
```

---

## Task 4: `enrich_content_item` — the enrichment orchestrator

**Files:**
- Create: `apps/backend/app/services/content.py`
- Test: `apps/backend/tests/test_content_enrichment.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_content_enrichment.py`:

```python
"""Tests for content enrichment."""
from __future__ import annotations

from app.models.content import ContentItem
from app.models.core import Event
from app.schemas.content import VideoIngredients
from app.services import content, llm
from app.services.youtube import VideoDetails


def _make_item(db, *, body="A recipe with tomato and rice.", metadata=None):
    item = ContentItem(
        provider="youtube",
        external_id="vid123",
        title="One-Pot Tomato Rice",
        url="https://www.youtube.com/watch?v=vid123",
        body=body,
        metadata_=metadata or {},
    )
    db.add(item)
    db.flush()
    return item


def test_enrich_content_item_writes_ingredients_and_metadata(db, monkeypatch):
    monkeypatch.setattr(
        llm,
        "extract_video_ingredients",
        lambda title, description, tags: VideoIngredients(
            is_recipe_video=True, dish_name="Tomato Rice", ingredients=["tomato", "rice"]
        ),
    )
    item = _make_item(db)
    ok = content.enrich_content_item(db, item)
    assert ok is True
    assert item.metadata_["is_recipe_video"] is True
    assert item.summary == "Tomato Rice"
    assert set(item.tags) == {"tomato", "rice"}
    # "tomato" and "rice" are seeded starter ingredients → both resolve to IDs.
    assert len(item.metadata_["ingredient_ids"]) == 2
    assert "enrichment" in item.metadata_
    events = db.query(Event).filter(Event.event_type == "content.item.enriched").all()
    assert len(events) == 1


def test_enrich_content_item_fetches_details_when_body_missing(db, monkeypatch):
    monkeypatch.setattr(
        content,
        "fetch_video_details",
        lambda video_id: VideoDetails(
            title="t", author="a", description="Uses rice.", youtube_tags=["rice"],
            duration_seconds=120, published_at=None,
        ),
    )
    monkeypatch.setattr(
        llm,
        "extract_video_ingredients",
        lambda title, description, tags: VideoIngredients(
            is_recipe_video=True, dish_name=None, ingredients=["rice"]
        ),
    )
    item = _make_item(db, body=None)
    ok = content.enrich_content_item(db, item)
    assert ok is True
    assert item.body == "Uses rice."
    assert item.duration_seconds == 120


def test_enrich_content_item_is_best_effort_on_llm_failure(db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(llm, "extract_video_ingredients", boom)
    item = _make_item(db)
    ok = content.enrich_content_item(db, item)
    assert ok is False
    assert "enrichment" not in item.metadata_  # left un-enriched
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_content_enrichment.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.content'`.

- [ ] **Step 3: Create `content.py` with `enrich_content_item`**

Create `apps/backend/app/services/content.py`:

```python
"""
Content enrichment + pantry-fit ranking.

Enrichment runs once per video: fetch the YouTube description (if not already
stored), ask Claude for the ingredient list, resolve those to canonical
food.ingredients IDs, and store everything on the ContentItem. Ranking is
rule-based set overlap against the live pantry — no LLM call, per request.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.models.content import ContentItem
from app.models.core import Household
from app.models.food import Ingredient, PantryItem
from app.services import llm
from app.services.events import emit_event
from app.services.ingredients import resolve_ingredient
from app.services.youtube import fetch_video_details

logger = logging.getLogger(__name__)

_ENRICHMENT_VERSION = 1
_EXPIRING_SOON_DAYS = 3
_EXPIRING_WEIGHT = 2.0  # a pantry ingredient expiring soon scores this; others 1.0


def enrich_content_item(db: Session, item: ContentItem) -> bool:
    """Enrich one ContentItem with extracted ingredients. Best-effort + idempotent.

    Returns True on success. On any failure, logs and returns False — the item is
    left un-enriched (no `metadata_["enrichment"]`) so the backfill can retry it.
    No DB flush happens on the failure path, so the session is never poisoned.
    """
    try:
        # Step 1: ensure the description text is present (old items lack it).
        if not item.body:
            details = fetch_video_details(item.external_id)
            if details is not None:
                item.body = details.description
                item.duration_seconds = details.duration_seconds
                if details.published_at is not None:
                    item.published_at = details.published_at
                item.metadata_ = {**item.metadata_, "youtube_tags": details.youtube_tags}

        youtube_tags = list(item.metadata_.get("youtube_tags") or [])

        # Step 2: extract ingredients via Claude.
        extracted = llm.extract_video_ingredients(item.title, item.body or "", youtube_tags)

        # Step 3: resolve to canonical ingredient IDs (keep all names as display tags).
        ingredient_ids: list[str] = []
        for name in extracted.ingredients:
            resolved = resolve_ingredient(db, name)
            if resolved is not None:
                ingredient_ids.append(str(resolved))

        item.tags = list(extracted.ingredients)
        if extracted.dish_name:
            item.summary = extracted.dish_name
        item.metadata_ = {
            **item.metadata_,
            "ingredient_ids": ingredient_ids,
            "is_recipe_video": extracted.is_recipe_video,
            "enrichment": {
                "version": _ENRICHMENT_VERSION,
                "enriched_at": datetime.now(UTC).isoformat(),
            },
        }
        db.flush()
        emit_event(
            db,
            event_type="content.item.enriched",
            entity_type="content_item",
            entity_id=item.id,
            payload={
                "is_recipe_video": extracted.is_recipe_video,
                "ingredient_count": len(ingredient_ids),
            },
        )
        return True
    except Exception:  # noqa: BLE001 — enrichment is best-effort, never fatal
        logger.exception("enrichment failed for content item %s", item.id)
        return False
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_content_enrichment.py -v`
Expected: PASS — 3 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/services/content.py apps/backend/tests/test_content_enrichment.py
git commit -m "feat(content): add video enrichment orchestrator"
```

---

## Task 5: Pantry-fit ranking + backfill

**Files:**
- Modify: `apps/backend/app/services/content.py`
- Test: `apps/backend/tests/test_content_ranking.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_content_ranking.py`:

```python
"""Tests for pantry-fit ranking and the enrichment backfill."""
from __future__ import annotations

from datetime import date, timedelta

from app.auth import DEV_HOUSEHOLD_ID
from app.models.content import ContentItem
from app.models.core import Household
from app.models.food import Ingredient, PantryItem
from app.schemas.content import VideoIngredients
from app.services import content, llm


def _ingredient_id(db, canonical: str):
    return db.query(Ingredient.id).filter(Ingredient.canonical_name == canonical).scalar()


def _video(db, *, title, ingredient_ids, is_recipe=True):
    item = ContentItem(
        provider="youtube",
        external_id=f"v-{title}",
        title=title,
        metadata_={
            "ingredient_ids": [str(i) for i in ingredient_ids],
            "is_recipe_video": is_recipe,
            "enrichment": {"version": 1, "enriched_at": "2026-05-21T00:00:00+00:00"},
        },
    )
    db.add(item)
    db.flush()
    return item


def _pantry(db, ingredient_id, *, expires_in_days=None):
    household = db.get(Household, DEV_HOUSEHOLD_ID)
    expires = date.today() + timedelta(days=expires_in_days) if expires_in_days is not None else None
    db.add(
        PantryItem(
            household_id=household.id,
            ingredient_id=ingredient_id,
            raw_name="x",
            expires_at=expires,
        )
    )
    db.flush()


def test_rank_orders_by_overlap_and_excludes_zero_match(db):
    household = db.get(Household, DEV_HOUSEHOLD_ID)
    tomato = _ingredient_id(db, "tomato")
    rice = _ingredient_id(db, "rice")
    egg = _ingredient_id(db, "egg")
    _pantry(db, tomato)
    _pantry(db, rice)
    two_match = _video(db, title="Tomato Rice", ingredient_ids=[tomato, rice])
    one_match = _video(db, title="Tomato Toast", ingredient_ids=[tomato])
    _video(db, title="Egg Curry", ingredient_ids=[egg])  # zero overlap → excluded

    ranked, pantry_size = content.rank_videos_for_pantry(db, household=household, limit=12)
    assert pantry_size == 2
    assert [r.item.id for r in ranked] == [two_match.id, one_match.id]


def test_rank_weights_expiring_ingredients(db):
    household = db.get(Household, DEV_HOUSEHOLD_ID)
    tomato = _ingredient_id(db, "tomato")
    _pantry(db, tomato, expires_in_days=1)  # expiring soon
    video = _video(db, title="Tomato Soup", ingredient_ids=[tomato])
    ranked, _ = content.rank_videos_for_pantry(db, household=household, limit=12)
    assert ranked[0].match_score >= 2.0  # expiring weight applied
    assert "expire" in ranked[0].match_reason.lower()


def test_rank_excludes_non_recipe_videos(db):
    household = db.get(Household, DEV_HOUSEHOLD_ID)
    tomato = _ingredient_id(db, "tomato")
    _pantry(db, tomato)
    _video(db, title="Not cooking", ingredient_ids=[tomato], is_recipe=False)
    ranked, _ = content.rank_videos_for_pantry(db, household=household, limit=12)
    assert ranked == []


def test_enrich_pending_processes_unenriched_only(db, monkeypatch):
    monkeypatch.setattr(
        llm,
        "extract_video_ingredients",
        lambda title, description, tags: VideoIngredients(
            is_recipe_video=True, dish_name=None, ingredients=["rice"]
        ),
    )
    # one already-enriched, one not
    _video(db, title="Enriched", ingredient_ids=[])
    raw = ContentItem(provider="youtube", external_id="raw1", title="Raw Rice Bowl", body="rice")
    db.add(raw)
    db.flush()

    result = content.enrich_pending(db, limit=10)
    assert result.enriched == 1
    assert result.remaining == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_content_ranking.py -v`
Expected: FAIL — `AttributeError: module 'app.services.content' has no attribute 'rank_videos_for_pantry'`.

- [ ] **Step 3: Add ranking + backfill to `content.py`**

Append to `apps/backend/app/services/content.py`:

```python
@dataclass
class RankedVideo:
    item: ContentItem
    match_score: float
    matched_ingredients: list[str]  # canonical display names
    match_reason: str


@dataclass
class EnrichResult:
    enriched: int
    failed: int
    remaining: int


def _join_names(names: list[str]) -> str:
    """'a' / 'a and b' / 'a, b, and c'."""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{', '.join(names[:-1])}, and {names[-1]}"


def _match_reason(matched_names: list[str], soonest: tuple[str, int] | None) -> str:
    base = f"Uses {_join_names(matched_names)}"
    if soonest is None:
        return base
    name, days = soonest
    when = "today" if days <= 0 else f"in {days} day{'s' if days != 1 else ''}"
    return f"{base} — {name} expires {when}"


def rank_videos_for_pantry(
    db: Session, *, household: Household, limit: int = 12
) -> tuple[list[RankedVideo], int]:
    """Rank enriched cooking videos by ingredient overlap with the household's pantry.

    Returns (videos sorted best-first, pantry_size). Zero-overlap videos are dropped.
    """
    # Pantry: ingredient_id -> soonest expiry in days (None = no expiry).
    today = date.today()
    pantry: dict[uuid.UUID, int | None] = {}
    pantry_rows = (
        db.query(PantryItem)
        .filter(
            PantryItem.household_id == household.id,
            PantryItem.deleted_at.is_(None),
            PantryItem.ingredient_id.isnot(None),
        )
        .all()
    )
    for row in pantry_rows:
        days = (row.expires_at - today).days if row.expires_at else None
        if row.ingredient_id not in pantry:
            pantry[row.ingredient_id] = days
        else:
            prev = pantry[row.ingredient_id]
            if days is not None and (prev is None or days < prev):
                pantry[row.ingredient_id] = days

    if not pantry:
        return [], 0

    names_by_id = {r.id: r.display_name for r in db.query(Ingredient).all()}

    items = (
        db.query(ContentItem)
        .filter(ContentItem.deleted_at.is_(None))
        .all()
    )
    ranked: list[RankedVideo] = []
    for item in items:
        meta = item.metadata_ or {}
        if not meta.get("is_recipe_video"):
            continue
        try:
            video_ids = {uuid.UUID(x) for x in meta.get("ingredient_ids") or []}
        except (ValueError, TypeError):
            continue
        matched = video_ids & set(pantry.keys())
        if not matched:
            continue

        score = 0.0
        expiring: list[tuple[str, int]] = []
        matched_names: list[str] = []
        for ing_id in matched:
            name = names_by_id.get(ing_id, "an ingredient")
            matched_names.append(name)
            days = pantry[ing_id]
            if days is not None and days <= _EXPIRING_SOON_DAYS:
                score += _EXPIRING_WEIGHT
                expiring.append((name, days))
            else:
                score += 1.0

        matched_names.sort()
        soonest = min(expiring, key=lambda x: x[1]) if expiring else None
        ranked.append(
            RankedVideo(
                item=item,
                match_score=score,
                matched_ingredients=matched_names,
                match_reason=_match_reason(matched_names, soonest),
            )
        )

    ranked.sort(key=lambda r: r.match_score, reverse=True)
    return ranked[:limit], len(pantry)


def enrich_pending(db: Session, *, limit: int = 20) -> EnrichResult:
    """Backfill: enrich up to `limit` ContentItems with no enrichment metadata.

    Flushes via `enrich_content_item`; the caller is responsible for the commit.
    """
    candidates = (
        db.query(ContentItem).filter(ContentItem.deleted_at.is_(None)).all()
    )
    todo = [it for it in candidates if not (it.metadata_ or {}).get("enrichment")]
    batch = todo[:limit]
    enriched = 0
    failed = 0
    for item in batch:
        if enrich_content_item(db, item):
            enriched += 1
        else:
            failed += 1
    return EnrichResult(
        enriched=enriched, failed=failed, remaining=max(0, len(todo) - len(batch))
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_content_ranking.py -v`
Expected: PASS — 4 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/services/content.py apps/backend/tests/test_content_ranking.py
git commit -m "feat(content): add pantry-fit ranking and enrichment backfill"
```

---

## Task 6: Rewrite the capture handler

The capture handler switches from a bare oEmbed call to `resolve_video_metadata` (one
YouTube call, Data-API-first) and enriches new items. `test_content.py`'s mocks must be
updated to match, or its existing tests break.

**Files:**
- Modify: `apps/backend/app/routers/content.py`
- Modify: `apps/backend/tests/test_content.py`

- [ ] **Step 1: Update `test_content.py` mocks to the new capture contract**

In `apps/backend/tests/test_content.py`, change the import line:

```python
from app.services.youtube import YouTubeMetadata, parse_video_id
```

to:

```python
from app.services.youtube import VideoMetadata, parse_video_id
```

Replace the `mock_youtube` fixture with:

```python
@pytest.fixture
def mock_youtube(monkeypatch):
    """Deterministic metadata + no-op enrichment, so capture tests stay offline/fast."""

    def fake_resolve(url: str) -> VideoMetadata:
        video_id = parse_video_id(url)
        assert video_id is not None
        return VideoMetadata(
            video_id=video_id,
            url=f"https://www.youtube.com/watch?v={video_id}",
            title=f"Frugal cooking — {video_id}",
            author="Test Channel",
            thumbnail_url=f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            description="A simple frugal recipe.",
        )

    monkeypatch.setattr(content_router, "resolve_video_metadata", fake_resolve)
    monkeypatch.setattr(content_router, "enrich_content_item", lambda db, item: True)
    return fake_resolve
```

Replace the body of `test_capture_propagates_unresolvable_video` with:

```python
def test_capture_propagates_unresolvable_video(client, monkeypatch):
    def boom(url: str):
        raise ValueError("YouTube could not resolve that video (private or removed?)")

    monkeypatch.setattr(content_router, "resolve_video_metadata", boom)
    resp = client.post("/api/v1/content/capture", json={"url": VIDEO_A})
    assert resp.status_code == 422
    assert "private or removed" in resp.json()["detail"]
```

Leave every other test in the file unchanged.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_content.py -v`
Expected: FAIL — the suite references `content_router.resolve_video_metadata` / `enrich_content_item`, which the router doesn't import yet (`AttributeError`).

- [ ] **Step 3: Rewrite the capture handler**

In `apps/backend/app/routers/content.py`, change the imports. The current lines are:

```python
from app.schemas.content import CaptureRequest, ContentItemRead, FeedResponse
from app.services.events import emit_event
from app.services.youtube import fetch_youtube_metadata, parse_video_id
```

Replace them with:

```python
from app.schemas.content import CaptureRequest, ContentItemRead, FeedResponse
from app.services.content import enrich_content_item
from app.services.events import emit_event
from app.services.youtube import parse_video_id, resolve_video_metadata
```

Then replace the entire `capture` function with:

```python
@router.post("/capture", response_model=ContentItemRead)
def capture(
    request: CaptureRequest,
    household: CurrentHousehold,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ContentItemRead:
    """Capture a YouTube video by URL into the shared content feed, then enrich it.

    Metadata resolves via the YouTube Data API (one call, rich) with an oEmbed
    fallback. Enrichment (ingredient extraction) is best-effort — a failure logs
    and leaves the item un-enriched; the capture still succeeds.
    """
    if parse_video_id(request.url) is None:
        raise HTTPException(422, "Only YouTube video URLs are supported right now")

    try:
        meta = resolve_video_metadata(request.url)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    existing = (
        db.query(ContentItem)
        .filter(
            ContentItem.provider == "youtube",
            ContentItem.external_id == meta.video_id,
        )
        .one_or_none()
    )
    if existing is not None:
        if existing.deleted_at is not None:
            existing.deleted_at = None  # re-capture an item that was removed
            db.commit()
            db.refresh(existing)
            logger.info("content item restored on re-capture: external_id=%s", meta.video_id)
        return ContentItemRead.model_validate(existing)

    item = ContentItem(
        provider="youtube",
        external_id=meta.video_id,
        title=meta.title,
        url=meta.url,
        author=meta.author,
        thumbnail_url=meta.thumbnail_url,
        topic=request.topic,
        body=meta.description,
        duration_seconds=meta.duration_seconds,
        published_at=meta.published_at,
        metadata_={"youtube_tags": meta.youtube_tags},
    )
    db.add(item)
    db.flush()

    emit_event(
        db,
        event_type="content.item.captured",
        household_id=household.id,
        user_id=user.id,
        entity_type="content_item",
        entity_id=item.id,
        payload={
            "provider": "youtube",
            "external_id": meta.video_id,
            "title": meta.title,
            "topic": request.topic,
        },
    )

    # Best-effort enrichment — `body` is already set, so this makes no extra
    # YouTube call; a failure inside is caught and never fails the capture.
    enrich_content_item(db, item)

    db.commit()
    db.refresh(item)
    logger.info("content item captured: external_id=%s topic=%s", meta.video_id, request.topic)
    return ContentItemRead.model_validate(item)
```

Leave `feed`, `delete_item`, and the `/sources` and `/ingest/run` stubs unchanged.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_content.py -v`
Expected: PASS — all pre-existing content tests, now against the new capture flow.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/routers/content.py apps/backend/tests/test_content.py
git commit -m "feat(content): enrich videos at capture via the Data API resolver"
```

---

## Task 7: Recipe-suggestions + enrich endpoints

**Files:**
- Modify: `apps/backend/app/routers/content.py`
- Test: `apps/backend/tests/test_recipe_suggestions_api.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_recipe_suggestions_api.py`:

```python
"""End-to-end tests for the recipe-suggestions and enrich endpoints."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth import DEV_HOUSEHOLD_ID
from app.db import SessionLocal
from app.main import app
from app.models.content import ContentItem
from app.models.food import Ingredient, PantryItem
from app.schemas.content import VideoIngredients
from app.services import llm


@pytest.fixture
def client():
    return TestClient(app)


def _seed_pantry_and_video():
    with SessionLocal() as db:
        tomato = db.query(Ingredient.id).filter(Ingredient.canonical_name == "tomato").scalar()
        db.add(
            PantryItem(
                household_id=DEV_HOUSEHOLD_ID,
                ingredient_id=tomato,
                raw_name="tomatoes",
                expires_at=date.today() + timedelta(days=1),
            )
        )
        db.add(
            ContentItem(
                provider="youtube",
                external_id="sug1",
                title="Tomato Soup",
                metadata_={
                    "ingredient_ids": [str(tomato)],
                    "is_recipe_video": True,
                    "enrichment": {"version": 1, "enriched_at": "2026-05-21T00:00:00+00:00"},
                },
            )
        )
        db.commit()


def test_recipe_suggestions_returns_pantry_matches(client):
    _seed_pantry_and_video()
    resp = client.get("/api/v1/content/recipe-suggestions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pantry_size"] == 1
    assert len(body["suggestions"]) == 1
    assert body["suggestions"][0]["title"] == "Tomato Soup"
    assert "tomato" in body["suggestions"][0]["match_reason"].lower()


def test_recipe_suggestions_empty_when_no_pantry(client):
    resp = client.get("/api/v1/content/recipe-suggestions")
    assert resp.status_code == 200
    assert resp.json() == {"suggestions": [], "pantry_size": 0}


def test_enrich_endpoint_processes_pending(client, monkeypatch):
    monkeypatch.setattr(
        llm,
        "extract_video_ingredients",
        lambda title, description, tags: VideoIngredients(
            is_recipe_video=True, dish_name=None, ingredients=["rice"]
        ),
    )
    with SessionLocal() as db:
        db.add(ContentItem(provider="youtube", external_id="raw9", title="Rice Bowl", body="rice"))
        db.commit()
    resp = client.post("/api/v1/content/enrich")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enriched"] == 1
    assert body["remaining"] == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_recipe_suggestions_api.py -v`
Expected: FAIL — `GET /api/v1/content/recipe-suggestions` returns 404 (route not defined).

- [ ] **Step 3: Add the endpoints**

In `apps/backend/app/routers/content.py`, extend the schema and service imports. Change:

```python
from app.schemas.content import CaptureRequest, ContentItemRead, FeedResponse
from app.services.content import enrich_content_item
```

to:

```python
from app.schemas.content import (
    CaptureRequest,
    ContentItemRead,
    EnrichResponse,
    FeedResponse,
    RecipeSuggestion,
    RecipeSuggestionsResponse,
)
from app.services.content import enrich_content_item, enrich_pending, rank_videos_for_pantry
```

Then add these two endpoints (place them after the `feed` endpoint, before `capture`):

```python
@router.get("/recipe-suggestions", response_model=RecipeSuggestionsResponse)
def recipe_suggestions(
    household: CurrentHousehold,
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(12, ge=1, le=50, description="Max suggestions to return."),
) -> RecipeSuggestionsResponse:
    """Saved cooking videos ranked by how well they fit the household's pantry."""
    ranked, pantry_size = rank_videos_for_pantry(db, household=household, limit=limit)
    return RecipeSuggestionsResponse(
        suggestions=[
            RecipeSuggestion(
                id=r.item.id,
                provider=r.item.provider,
                external_id=r.item.external_id,
                title=r.item.title,
                url=r.item.url,
                author=r.item.author,
                thumbnail_url=r.item.thumbnail_url,
                duration_seconds=r.item.duration_seconds,
                match_score=r.match_score,
                matched_ingredients=r.matched_ingredients,
                match_reason=r.match_reason,
            )
            for r in ranked
        ],
        pantry_size=pantry_size,
    )


@router.post("/enrich", response_model=EnrichResponse)
def enrich_pending_endpoint(
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(20, ge=1, le=100, description="Max items to enrich this call."),
) -> EnrichResponse:
    """Backfill enrichment for videos saved before this feature. Bounded by `limit`;
    re-call while `remaining > 0`."""
    result = enrich_pending(db, limit=limit)
    db.commit()
    return EnrichResponse(
        enriched=result.enriched, failed=result.failed, remaining=result.remaining
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_recipe_suggestions_api.py -v`
Expected: PASS — 3 tests.

Then run the full backend suite: `uv run pytest -q` — expect all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/routers/content.py apps/backend/tests/test_recipe_suggestions_api.py
git commit -m "feat(content): add recipe-suggestions and enrich endpoints"
```

---

## Task 8: Frontend — "Cook from your pantry" on `/watch`

**Files:**
- Modify: `apps/web/src/lib/types.ts`
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/app/watch/page.tsx`

- [ ] **Step 1: Add the frontend types**

Append to `apps/web/src/lib/types.ts`:

```typescript
// ---------- Recipe suggestions ----------

export interface RecipeSuggestion {
  id: string;
  provider: string;
  external_id: string;
  title: string;
  url: string | null;
  author: string | null;
  thumbnail_url: string | null;
  duration_seconds: number | null;
  match_score: number;
  matched_ingredients: string[];
  match_reason: string;
}

export interface RecipeSuggestionsResponse {
  suggestions: RecipeSuggestion[];
  pantry_size: number;
}
```

- [ ] **Step 2: Add the API client function**

In `apps/web/src/lib/api.ts`, add `RecipeSuggestionsResponse` to the `import type { ... } from "./types"` list (alphabetically among the `R…` names). Then append to the end of the file:

```typescript
export function getRecipeSuggestions(
  limit = 12,
): Promise<RecipeSuggestionsResponse> {
  return api<RecipeSuggestionsResponse>(
    `/api/v1/content/recipe-suggestions?limit=${limit}`,
  );
}
```

- [ ] **Step 3: Add the suggestions section to the watch page**

In `apps/web/src/app/watch/page.tsx`:

Change the import line:

```typescript
import { captureVideo, deleteContentItem, getContentFeed } from "@/lib/api";
import type { ContentItem } from "@/lib/types";
```

to:

```typescript
import {
  captureVideo,
  deleteContentItem,
  getContentFeed,
  getRecipeSuggestions,
} from "@/lib/api";
import type { ContentItem, RecipeSuggestion } from "@/lib/types";
```

Add a suggestions state declaration directly after the `items` state line
(`const [items, setItems] = useState<ContentItem[]>([]);`):

```typescript
  const [suggestions, setSuggestions] = useState<RecipeSuggestion[]>([]);
```

Replace the existing `useEffect` block with one that fetches both concurrently:

```typescript
  useEffect(() => {
    Promise.all([
      getContentFeed().catch(() => ({ items: [], count: 0 })),
      getRecipeSuggestions().catch(() => ({ suggestions: [], pantry_size: 0 })),
    ])
      .then(([feed, sugg]) => {
        setItems(feed.items);
        setSuggestions(sugg.suggestions);
      })
      .finally(() => setLoading(false));
  }, []);
```

Add the suggestions section to the render tree — place it immediately after the
`<div className="rule-fade mb-8" />` line and before the `{loading ? (` feed block:

```tsx
      {!loading && suggestions.length > 0 && (
        <section className="mb-10">
          <p className="eyebrow text-clay">Cook from your pantry</p>
          <p className="mt-1 mb-4 text-[13px] text-ink-soft">
            Saved videos that use what you have on hand.
          </p>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {suggestions.map((s) => (
              <SuggestionCard key={s.id} suggestion={s} />
            ))}
          </div>
        </section>
      )}
```

Add the `SuggestionCard` component — place it after the existing `VideoCard`
component definition:

```tsx
function SuggestionCard({ suggestion }: { suggestion: RecipeSuggestion }) {
  return (
    <a
      href={suggestion.url ?? "#"}
      target="_blank"
      rel="noreferrer"
      className="group overflow-hidden rounded-xl border border-clay/25 bg-raised shadow-warm transition-all hover:-translate-y-0.5 hover:shadow-warm-lg"
    >
      <div className="relative aspect-video bg-crust">
        {suggestion.thumbnail_url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={suggestion.thumbnail_url}
            alt={suggestion.title}
            className="h-full w-full object-cover"
          />
        )}
      </div>
      <div className="p-4">
        <h3 className="line-clamp-2 text-[15px] font-semibold leading-snug text-ink">
          {suggestion.title}
        </h3>
        <p className="mt-1.5 text-[12px] font-medium text-clay-deep">
          {suggestion.match_reason}
        </p>
      </div>
    </a>
  );
}
```

- [ ] **Step 4: Verify the frontend typechecks**

Run (from `apps/web/`): `pnpm typecheck`
Expected: PASS — no type errors.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/types.ts apps/web/src/lib/api.ts apps/web/src/app/watch/page.tsx
git commit -m "feat(web): add Cook from your pantry section to the watch library"
```

---

## Task 9: Full verification

**Files:** none (verification only — commit only if fixes are needed).

- [ ] **Step 1: Full backend test suite**

Run (from `apps/backend/`): `uv run pytest`
Expected: PASS — all prior tests plus the new `test_content_schemas`, `test_video_ingredients`, `test_content_enrichment`, `test_content_ranking`, `test_recipe_suggestions_api` tests, and the updated `test_content` / `test_youtube`. If anything fails, fix the root cause and re-run.

- [ ] **Step 2: Backend lint + format + type check**

Run (from `apps/backend/`): `uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: clean. Fix issues in this feature's files only (`ruff check . --fix` for auto-fixable; `ruff format .` to format). For `mypy`, fix with correct annotations — no blanket `# type: ignore`. If `mypy` reports a *pre-existing* error in a file this feature never touched (`git diff main...HEAD --name-only` to confirm), leave it and note it.

- [ ] **Step 3: Frontend type check**

Run (from `apps/web/`): `pnpm typecheck`
Expected: PASS.

- [ ] **Step 4: Commit any fixes**

If Steps 1-3 required changes:

```bash
git add -A
git commit -m "fix: address verification findings for pantry video suggestions"
```

Otherwise make no commit.

---

## Task 10: Documentation

**Files:**
- Modify: `docs/architecture.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Document the new event type**

In `docs/architecture.md`, find rule 6 ("Activity through `core.events`"), which lists the
known food-tier event types. Add `content.item.enriched` to that enumeration (it is a
content-tier event — emitted when a saved video is enriched with extracted ingredients).
Match the existing inline style.

- [ ] **Step 2: Update `CLAUDE.md`**

In `CLAUDE.md`, update the "Current state" section's `content` entry under "What's fully
implemented" to note pantry-aware recipe suggestions, e.g.:

`**`content`** — YouTube link capture + feed; videos are enriched at capture (YouTube Data API description + AI ingredient extraction) and the `/watch` library ranks them by pantry fit via `GET /content/recipe-suggestions`. Channel/RSS/Reddit polling still stubbed.`

Keep the edit minimal and in the file's existing style.

- [ ] **Step 3: Commit**

```bash
git add docs/architecture.md CLAUDE.md
git commit -m "docs: note pantry-aware video suggestions"
```

---

## Self-review notes

- **Spec coverage:** schemas → T1; Data-API-first one-call resolver → T2; `extract_video_ingredients` → T3; `enrich_content_item` (self-sufficient fetch-if-missing) → T4; rule-based ranking + bounded backfill → T5; capture rewrite + `test_content.py` mock update → T6; `recipe-suggestions` + `enrich` endpoints → T7; concurrent-fetch `/watch` section → T8; `content.item.enriched` event → T4 + T10.
- **No migration:** all data lands in existing `ContentItem` columns (`body`, `summary`, `duration_seconds`, `published_at`, `tags`, `metadata_`) — confirmed against `app/models/content.py`.
- **Ripple effect handled:** changing capture breaks `test_content.py`'s `fetch_youtube_metadata` mock; T6 Step 1 updates the fixture to patch `resolve_video_metadata` + `enrich_content_item` before the implementation step.
- **Best-effort enrichment:** `enrich_content_item` flushes only on the success path, so a caught failure never poisons the session for the capture commit or the backfill loop.
- **Graceful degradation:** no API key → `fetch_video_details` returns None → oEmbed fallback → title-only extraction; all covered by T2/T4 tests.
