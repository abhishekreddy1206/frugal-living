# Pantry-Aware Recipe Suggestions — Design Spec

**Date:** 2026-05-21
**Status:** Approved for planning
**Scope:** Make the `/watch` video library surface saved cooking videos ranked by how well
their ingredients match the household's current pantry, weighting items that expire soon.

---

## 1. Problem

The `/watch` library lets a household save YouTube videos (`POST /api/v1/content/capture`,
metadata via oEmbed) into a shared catalog. It is an inert list — newest first, nothing
more. The user wants it to *suggest what to cook from what they already have*: a "Cook from
your pantry" view that ranks their saved cooking videos by pantry fit, automatically.

The data model already anticipates this: `content.items` has `tags`, `body`,
`duration_seconds`, `relevance_score`, and a JSONB `metadata_` column, and `llm.py` carries
a `rank_content_for_household` stub. The feature is half-scaffolded; this spec finishes it.

## 2. Approach

Two stages, deliberately separated so cost lands once and ranking stays free:

1. **Enrichment (once per video).** When a video is saved, fetch its description + the
   uploader's tags via the YouTube Data API, ask Claude to extract the ingredient list and
   classify whether it is a cooking video, resolve each ingredient to a canonical
   `food.ingredients` ID via the existing `resolve_ingredient` resolver, and store all of
   that on the `ContentItem`. This is household-agnostic and happens exactly once per video.

2. **Ranking (per request, rule-based).** When `/watch` loads, score each cooking video by
   the overlap between its canonical ingredient IDs and the household's current pantry
   ingredient IDs, weighting soon-expiring pantry items. Pure set arithmetic over a small
   catalog — no LLM call, instant, deterministic. Pantry-fit scores are **not persisted**
   (`ContentItem` is a global shared catalog; pantry fit is per-household and ephemeral).

Matching is exact because both sides resolve to the same canonical ingredient IDs: a pantry
"Roma tomatoes" and a video's "tomato" both resolve to the `tomato` ingredient.

### Signal limits (accepted)

- The YouTube Data API reliably returns a video's **title, description, uploader tags,
  category, duration, publish date**. It does **not** practically return captions /
  transcripts (caption download requires per-video owner OAuth). v1's text signal is
  therefore **title + description + uploader tags**. Real transcripts are out of scope.
- Matching quality is bounded by the canonical ingredient catalog (~33 starter
  ingredients). Ingredients outside it (e.g. "pancetta") resolve to no ID and do not
  contribute to matching, though they are still stored as display tags. Growing the catalog
  is a separate effort, out of scope here.

## 3. Efficiency decisions

- **One YouTube round-trip per capture.** The Data API `videos.list?part=snippet,
  contentDetails` response is a superset of oEmbed (it includes title, channel, thumbnails,
  description, tags, duration, publish date). So when `YOUTUBE_API_KEY` is configured,
  capture makes a **single** Data API call — not oEmbed *and* the Data API. oEmbed is the
  fallback only when no key is configured. Thumbnails use the deterministic
  `https://i.ytimg.com/vi/{id}/hqdefault.jpg` URL regardless of source.
- **Ranking is rule-based**, so it costs nothing per page view. The `rank_content_for_household`
  LLM stub is intentionally left unused — per-load AI ranking was rejected for cost.
- **`/watch` fetches the feed and the suggestions concurrently** (`Promise.all`), so the new
  section adds no serial latency.
- **The backfill endpoint is bounded** — it processes at most N items per call and reports
  how many remain, so it can never become an unbounded, timeout-prone request.

## 4. Data model — no migration

All data fits existing `content.items` columns (inviolable rule 3 — JSONB `metadata_` for
per-row fields without migrations):

| Field | Holds |
|---|---|
| `body` | the YouTube description (the rich matching text) |
| `summary` | the AI-extracted dish name, if any (short, human-readable) |
| `duration_seconds` | parsed from the Data API `contentDetails.duration` (ISO-8601) |
| `published_at` | the Data API `snippet.publishedAt` (currently left null on capture) |
| `metadata_["youtube_tags"]` | the uploader's raw YouTube tags — extra extraction signal, persisted so the backfill can re-run extraction without re-fetching |
| `tags` | extracted ingredient **display names** (also covers ingredients with no canonical ID) |
| `metadata_["ingredient_ids"]` | list of canonical `food.ingredients` UUIDs (as strings) |
| `metadata_["is_recipe_video"]` | bool — false ⇒ excluded from suggestions |
| `metadata_["enrichment"]` | `{version, enriched_at}` — presence marks an item as enriched |

No new columns; no Alembic migration. The global `relevance_score` column is left untouched
(pantry-fit is per-household and computed per request, never written to the shared item).

## 5. Backend components

### `app/services/youtube.py` (extend)

- `fetch_video_details(video_id) -> VideoDetails | None` — calls the YouTube Data API
  `videos.list` with `part=snippet,contentDetails` and `key=settings.youtube_api_key`.
  Returns a dataclass with `title`, `author`, `description`, `youtube_tags: list[str]`,
  `duration_seconds: int | None`, `published_at: datetime | None`. Returns `None` (logging a
  warning) when `YOUTUBE_API_KEY` is unset, the call fails, or the video id is not found —
  callers then fall back.
- `resolve_video_metadata(url) -> VideoMetadata` — the single entry point capture uses.
  Parses the video id, tries `fetch_video_details` first; on `None`, falls back to the
  existing oEmbed `fetch_youtube_metadata`. Returns a unified object carrying at minimum
  title/author/thumbnail/url, and (when the Data API succeeded) description/youtube_tags/
  duration/published_at. Raises `ValueError` only when *neither* source can resolve the
  video (→ HTTP 422), preserving today's capture error behaviour.

The existing `fetch_youtube_metadata` (oEmbed) and `parse_video_id` are kept as-is.

### `app/services/llm.py` (extend)

- `VIDEO_INGREDIENTS_SYSTEM` — versioned prompt (`# v0.1`). Instructs Claude to read a
  video's title + description + uploader tags and return strict JSON. Tells it to extract
  only the ingredients a cook would need, to use common ingredient names, and to set
  `is_recipe_video` false for non-cooking content (vlogs, finance tips, etc.).
- `extract_video_ingredients(title, description, youtube_tags) -> VideoIngredients` —
  `MODEL_FAST` (Sonnet); standard `get_client().messages.create(...)` → text → `_extract_json`
  → Pydantic-validate shape. `VideoIngredients` (Pydantic, in `schemas/content.py`):
  `is_recipe_video: bool`, `dish_name: str | None`, `ingredients: list[str]`.

### `app/services/content.py` (new)

- `enrich_content_item(db, item) -> bool` — the enrichment orchestrator, self-sufficient for
  both freshly-captured and pre-existing items. **Step 1:** if `item.body` is empty, call
  `fetch_video_details(item.external_id)` and populate `body` (description),
  `duration_seconds`, `published_at`, and `metadata_["youtube_tags"]` — this is what lets the
  backfill enrich videos saved before this feature (which have only title/author/thumbnail).
  **Step 2:** run `extract_video_ingredients` over title + `body` + `metadata_["youtube_tags"]`.
  **Step 3:** resolve each extracted ingredient name to a canonical ID via `resolve_ingredient`
  (dropping `None`s but keeping every name in `tags`); write `tags`, `summary`, and the
  remaining `metadata_` keys from §4; emit `content.item.enriched`. Returns whether
  enrichment succeeded. **Best-effort and idempotent:** any exception is caught and logged;
  the item is left un-enriched. Because the capture flow pre-populates `body` (§ below), the
  capture-time call skips Step 1's fetch — keeping capture to one YouTube call.
- `rank_videos_for_pantry(db, household, *, limit) -> list[RankedVideo]` — loads the
  household's non-deleted pantry items (their `ingredient_id`s and `expires_at`), loads
  non-deleted `ContentItem`s with `metadata_["is_recipe_video"] is true`, and scores each:
  `+1` per ingredient ID present in both the video and the pantry, with an extra weight for
  pantry items expiring within 3 days. Videos with a zero score are dropped. Returns the
  top `limit`, each with `match_score`, `matched_ingredients` (canonical display names from
  the `food.ingredients` rows), and a generated `match_reason` string (e.g. `"Uses spinach
  and eggs — spinach expires in 2 days"`). `match_reason` is assembled in code, no LLM.
- `enrich_pending(db, *, limit) -> EnrichResult` — backfill: finds up to `limit` non-deleted
  `ContentItem`s lacking `metadata_["enrichment"]`, calls `enrich_content_item` on each,
  returns `{enriched, failed, remaining}`.

### `app/routers/content.py` (modify)

- **Capture handler:** replace the standalone oEmbed call with `resolve_video_metadata`.
  Create the `ContentItem` with title/author/thumbnail/url plus — when the Data API
  succeeded — `body` (description), `duration_seconds`, `published_at`, and
  `metadata_["youtube_tags"]`. Then call `enrich_content_item` on the newly-created item,
  best-effort (a failure never fails the capture; the item is still returned). Because
  `body` is already populated, `enrich_content_item` skips its fetch step — the capture
  makes exactly one YouTube call. The re-capture/dedup path is unchanged and does not
  re-enrich (the backfill covers any un-enriched item).
- `GET /api/v1/content/recipe-suggestions?limit=` — `CurrentHousehold`; calls
  `rank_videos_for_pantry`; returns `RecipeSuggestionsResponse`.
- `POST /api/v1/content/enrich` — calls `enrich_pending` (bounded `limit`, default e.g. 20);
  returns `EnrichResponse`. One-time catch-up for videos saved before this feature.

### `app/schemas/content.py` (extend)

- `VideoIngredients` — LLM output: `is_recipe_video: bool`, `dish_name: str | None`,
  `ingredients: list[str]`.
- `RecipeSuggestion` — the `ContentItemRead` fields plus `match_score: float`,
  `matched_ingredients: list[str]`, `match_reason: str`.
- `RecipeSuggestionsResponse` — `suggestions: list[RecipeSuggestion]`, `pantry_size: int`.
- `EnrichResponse` — `enriched: int`, `failed: int`, `remaining: int`.

## 6. Enrichment timing

Enrichment runs **at capture time, synchronously, best-effort**. A capture becomes: one
YouTube metadata call + one `extract_video_ingredients` LLM call (~3–5 s total), covered by
the existing "Saving…" button state. Videos saved before this feature ships are caught up by
calling `POST /api/v1/content/enrich` (repeatedly if `remaining > 0`). Both paths share
`enrich_content_item`. No background queue is introduced (none exists; adding one needs
human sign-off per CLAUDE.md).

## 7. Events

`content.item.captured` already fires on capture. `enrich_content_item` emits
`content.item.enriched` on success (inviolable rule 5 — every meaningful mutation writes a
`core.events` row). `content.item.enriched` is a new event type.

## 8. Frontend — `/watch`

`apps/web/src/app/watch/page.tsx` gains a **"Cook from your pantry"** section above the
existing "Saved" grid:

- On load, the page fetches the feed and the suggestions **concurrently** (`Promise.all` over
  `getContentFeed()` and a new `getRecipeSuggestions()`).
- Each suggestion renders as a card: thumbnail, title, and a match-reason line
  ("Uses spinach + eggs — spinach expires in 2 days"). Styled distinctly from the plain grid
  (a warm accent header) so it reads as a recommendation.
- If the suggestions list is empty (empty pantry, or no enriched cooking video overlaps),
  the section is hidden entirely — the plain "Saved" library still renders.
- A suggestions fetch failure is swallowed (the section just doesn't appear); the saved feed
  is independent and unaffected.

`apps/web/src/lib/api.ts` + `types.ts` gain `getRecipeSuggestions()` and the matching types
(`RecipeSuggestion`, `RecipeSuggestionsResponse`).

## 9. Error handling / graceful degradation

- **No `YOUTUBE_API_KEY`** — `fetch_video_details` returns `None`; `resolve_video_metadata`
  falls back to oEmbed; enrichment runs `extract_video_ingredients` on the title alone
  (rougher, still functional). The feature works without a key, better with one.
- **LLM failure during enrichment** — caught and logged in `enrich_content_item`; the item
  is saved un-enriched and capture still returns 200. It simply won't appear in suggestions
  until re-enriched via the backfill.
- **`is_recipe_video: false`** — the item is enriched but excluded from ranking (correct: not
  a cooking video).
- **Empty pantry / no enriched videos** — `recipe-suggestions` returns an empty list (200);
  the frontend hides the section.
- **Unresolvable video at capture** — `resolve_video_metadata` raises `ValueError` → HTTP
  422, exactly as today.

## 10. Testing

Backend, with the LLM and `httpx` mocked per existing patterns (`tests/test_briefings.py`,
`tests/test_youtube.py`):

- `fetch_video_details` — mocked `httpx`: success parse; key-missing → `None`; HTTP error →
  `None`.
- `resolve_video_metadata` — Data API success path; Data-API-fails-falls-back-to-oEmbed
  path; both-fail → `ValueError`.
- `extract_video_ingredients` — mocked LLM: well-formed JSON; fenced JSON; non-recipe video.
- `enrich_content_item` — mocked youtube + LLM: the body-present path (no re-fetch) and the
  body-missing path (fetches details first); ingredient IDs resolved and written to
  `metadata_`/`tags`; `content.item.enriched` emitted; an LLM exception leaves the item
  un-enriched and does not raise.
- `rank_videos_for_pantry` — seed a pantry + several enriched videos: assert ordering by
  score, expiry weighting, exclusion of non-recipe videos and zero-overlap videos.
- `enrich_pending` — seed un-enriched items: assert bounded by `limit` and the
  `remaining` count.
- Endpoint smoke tests: `GET /recipe-suggestions` (with and without matches) and
  `POST /enrich`; capture still succeeds when enrichment fails.

Frontend: `pnpm typecheck`. No frontend test runner exists in this project; the `/watch`
section is verified by a manual browser smoke test.

## 11. Out of scope for v1

Real transcripts (needs a scraping library); recommending un-saved videos (needs YouTube
search); channel/RSS ingestion; persisting per-household relevance; growing the canonical
ingredient catalog; batching LLM extraction across videos.
