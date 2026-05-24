# Tier B Phase 2 — Community & Shareable Listings: Design Spec

**Date:** 2026-05-24
**Status:** Approved design. Next step: implementation plan via `writing-plans`.
**Parent:** `2026-05-21-tier-b-community-marketplace-design.md` (the Tier B roadmap — Phase 2 of 4).
**Depends on:** `2026-05-22-real-auth-multi-household-design.md` (real auth + multi-household — merged in `0bfeb6a`).

---

## 1. Context & goal

Phase 1 shipped private household inventory (`community.items`) and full chat parity. Real authentication and the active-household model are now in place — so multi-household reads are finally meaningful.

Phase 2 introduces the marketplace's read path: a user can join (with the community owner's approval) one or more communities; their household can opt items into **shareable listings** visible in those communities and/or within a geographic radius; other households browse a discovery feed. **No transactions yet** — borrow / swap / gift requests are Phase 3.

This is the first time the system supports household ↔ household visibility. Every read endpoint funnels through a single canonical visibility query (`services/community/visibility.py`) — the same pattern documented in the Tier B roadmap §5.3.

## 2. Decisions locked

| Decision | Choice |
|---|---|
| **Community membership** | Per-user. A community is a collection of `User`s; a household's listings appear in a community when **at least one current household member** is a current member of that community. |
| **Join model** | Request-to-join, owner approval. Communities are discoverable by slug (an out-of-band-shared handle like `park-slope-tools`). |
| **Listing creator** | Any household `owner` or `member` (not `viewer`). |
| **Listing edit scope** | Any household `owner` or `member` can edit *any* listing owned by their household (matches how shared household state works elsewhere). |
| **Listing → community picks** | Default = all the lister's current personal communities (each deselectable). On edit, added communities must be a subset of the *editor's* current memberships; existing picks may stay or be removed. |
| **`share_in_radius` default** | **`false`** (privacy-default-private). Radius sharing is an explicit opt-in. |
| **Geography unit** | Miles (US-focused). |
| **Default share radius** | 5 mi. |
| **Geography input** | Browser `navigator.geolocation` primary; a manual lat/lng entry is the fallback for users who decline the browser permission. **No geocoder dependency** (a geocoder is a deliberate Phase 4+ call per the inviolable rules). |
| **Location storage** | `core.households.metadata_` JSONB — `{lat: number, lng: number}`. Promote to indexed columns when radius queries prove hot (Rule 3). |
| **Location privacy** | Exact lat/lng is **never returned** to any API caller other than members of the owning household. Distance shown to other households is rounded to 0.1 mi. |
| **One listing per item** | A given inventory item has **at most one active listing**. Unique constraint enforced. Multiple exchange types live as an array on the single listing. |
| **Feed ranking (v1)** | Recency, newest first. LLM ranking deferred. |
| **Auth posture** | Inherited from `2026-05-22-real-auth-multi-household-design.md`: `SameSite=Lax` + CORS + non-GET mutations. No additional CSRF surface introduced. |

## 3. The visibility helper — the canonical access gate

`app/services/community/visibility.py` exports the single query every read endpoint funnels through. **All security audit fixes #1–#4 are encoded here.**

```python
def listings_visible_to(db, *, viewer_household: Household, viewer_user: User) -> Query[Listing]:
    """Listings visible to (viewer_household acting as viewer_user). Returns a Query
    so callers can layer .filter()/.order_by()/.limit() on top."""
```

The query satisfies all of the following simultaneously:

- The listing is **active**: `listings.deleted_at IS NULL AND listings.availability_status = 'available'`.
- The referenced item is **active**: `items.deleted_at IS NULL`.
- The owning household is **not** the viewer's own household (you don't browse your own listings on the feed).
- **At least one** of these holds:
  - **Community path:** the listing's `listing_communities` row matches a community where **at least one currently active member of the owning household** is also a currently active member of that community. (Audit fix #2 — re-check at read time.) AND that community's `deleted_at IS NULL`. (Audit fix #4.)
  - **Radius path:** `listings.share_in_radius = true` AND the distance between the owning household's lat/lng and the viewer's household's lat/lng (both from `households.metadata_`) is within the effective share radius, where **effective radius = COALESCE(listing.share_radius_miles, owning_household.metadata_.share_radius_miles, 5 mi global default)** — and the viewer's optional `radius_miles_max` query-param cap (if provided) further narrows. Distance is a bounding-box approximation on plain float comparisons (no PostGIS — stays within the inviolable rules at pre-launch scale).
- All `User` rows traversed in the membership join (the owning-household members AND the viewer themselves) satisfy `users.is_active = true`. (Audit fix #4.)

The viewer's lat/lng comes from `viewer_household.metadata_`; if unset, the radius path is a no-op (the viewer simply doesn't see radius-shared listings until they set their location).

## 4. Data model (`community` schema additions)

Phase 1 already created `community.items`. Three new tables, one join table, and a `core.households.metadata_` JSONB key.

### 4.1 `community.communities`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `slug` | String(80) | **unique**, lowercase URL handle (`park-slope-tools`). Validated `^[a-z0-9-]{2,80}$`. |
| `name` | String(200) | Human-readable. |
| `description` | Text, nullable | |
| `created_by_user_id` | FK `core.users.id` | not null |
| `metadata_` | JSONB | default `{}` |
| `created_at` / `updated_at` / `deleted_at` | via `TimestampMixin` | |

### 4.2 `community.community_members`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `community_id` | FK `community.communities.id` | not null |
| `user_id` | FK `core.users.id` | not null |
| `role` | String(32) | `owner` / `member`. Creator becomes `owner` on community creation. |
| `joined_at` | DateTime(tz) | `server_default=now()` |
| `metadata_` | JSONB | |
| `created_at` | DateTime(tz) | `server_default=now()` |

`UniqueConstraint(community_id, user_id)`. **No `deleted_at`** — leaving a community deletes the row; the historical record lives in `community.community_join_requests`. (Documented infrastructure-table exception, same rationale as `core.sessions`.)

### 4.3 `community.community_join_requests`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `community_id` | FK | not null |
| `user_id` | FK `core.users.id` | the requester, not null |
| `status` | String(16) | `pending` / `approved` / `declined` / `withdrawn` |
| `requested_at` | DateTime(tz) | `server_default=now()` |
| `decided_at` | DateTime(tz), nullable | |
| `decided_by_user_id` | FK `core.users.id`, nullable | the owner who approved/declined |
| `decision_note` | Text, nullable | optional reason |
| `metadata_` | JSONB | |

Partial unique index: `(community_id, user_id) WHERE status = 'pending'` — at most one open request per user per community.

### 4.4 `community.listings`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `item_id` | FK `community.items.id` | not null. The listing's owning household is **derived** through this FK (no `household_id` cache — audit fix #12). |
| `created_by_user_id` | FK `core.users.id` | not null |
| `allowed_exchange_types` | `ARRAY(String)` | subset of `{borrow, swap, gift}`, length ≥ 1 |
| `quantity_available` | Integer | 1..item.quantity (enforced server-side at create + on item updates — audit fix #7) |
| `share_in_radius` | Boolean | **default `false`** (audit fix #6) |
| `share_radius_miles` | Integer, nullable | per-listing override; if NULL, falls back to the owning household's `metadata_.share_radius_miles`, then to the global default (5 mi) |
| `availability_status` | String(16) | `available` / `paused` / `removed` |
| `description_override` | Text, nullable | |
| `metadata_` | JSONB | |
| `created_at` / `updated_at` / `deleted_at` | via `TimestampMixin` | |

**Partial unique index:** `(item_id) WHERE deleted_at IS NULL AND availability_status != 'removed'` — one active listing per item (audit fix #8). Editing changes its terms.

### 4.5 `community.listing_communities`

Many-to-many join. The explicit picks the lister made — used as a filter on top of (not a substitute for) the read-time membership check.

| Column | Type | Notes |
|---|---|---|
| `listing_id` | FK `community.listings.id` | composite PK |
| `community_id` | FK `community.communities.id` | composite PK |
| `added_by_user_id` | FK `core.users.id` | who added this pick |
| `created_at` | DateTime(tz) | `server_default=now()` |

`PrimaryKeyConstraint(listing_id, community_id)`. No `deleted_at` (removing a pick deletes the row).

### 4.6 `core.households.metadata_` — lat/lng key

No migration step required (JSONB extension). The application code reads / writes:

```
households.metadata_ = {
  ...existing keys,
  "lat": 40.6782,            # optional
  "lng": -73.9442,           # optional
  "share_radius_miles": 5    # optional household-level default; overrides the global default (5 mi)
                             # and is itself overridden by a per-listing share_radius_miles when set
}
```

When a household has no `lat`/`lng`, the radius path of the visibility query is a no-op for that household — they see and are seen only via communities.

## 5. Sync rules (the audit-driven cascades)

These are the read/write invariants the service layer enforces. **Tests must cover each.**

- **Item soft-delete cascades to listing** (audit fix #1). `services/community/items.soft_delete_item` is extended: if any active listing exists for the item, it is also soft-deleted (`deleted_at` set, `availability_status="removed"`) atomically in the same transaction.
- **Item quantity change reconciles listing** (audit fix #7). `services/community/items.update_item` is extended: when `quantity` changes, if the item has an active listing whose `quantity_available > new_quantity`, cap it; if new quantity is 0, soft-delete the listing.
- **Listing edit gates added communities** (audit fix #3). `services/community/listings.update_listing` validates that any `community_id` newly added to `listing_communities` is in the *editing user's* current `community_members`. Existing picks can stay or be removed by anyone in the household.
- **Member removal / community delete affects visibility on read, not write.** No DB cascade — the visibility query's read-time membership check (§3) naturally hides listings whose anchor memberships vanished. The stored `listing_communities` picks remain (historical / instantly re-visible on re-join).
- **Concurrent join-request approval is idempotent** (audit fix #10). The approve endpoint conditions on `status = 'pending'` in the `UPDATE`; if 0 rows updated, returns 409.

## 6. Authorization rules

| Action | Who | 4xx on failure |
|---|---|---|
| Create community | any authenticated user (becomes its `owner`) | — |
| Edit / soft-delete community, approve/decline join requests, remove a member (deferred) | community `owner` | 403 |
| Request to join, withdraw own request | any authenticated user | — |
| Leave community | any community `member` (an `owner` may not leave the only `owner`-row community — soft-delete instead — for v1) | 409 |
| List, edit, delete a listing | household `owner` or `member` (`viewer` cannot) | 403 |
| Browse feed / preview a community | any authenticated user (gets only what's visible) | — |

## 7. Security & privacy

The auth-feature CSRF posture (SameSite=Lax + CORS-locked origins + no GET mutations) is inherited; Phase 2 adds **no GET endpoints that mutate state**. Specific Phase 2 considerations:

- **Exact lat/lng is never returned** to any API caller other than members of the owning household. The household-self read (`GET /me`, an inventory page, etc.) sees the raw value; everyone else sees only `distance_miles` (rounded to 0.1) when the listing reaches them via the radius path.
- **Distance precision triangulation risk** (audit #14): rounding to 0.1 mi at very close range, combined with several visible listings, could narrow a household's location. Acceptable for v1 (hyperlocal trust + opt-in radius). Documented; revisit in Phase 4 with the trust layer.
- **Slug enumeration** (audit #13): `GET /communities/{slug}` returns existence + the public preview (name, description, member count, the caller's own join-request status). No member identities exposed. Per-IP/per-user rate limit deferred — acceptable for v1.
- **Community owner moderation actions write `core.audit_log`** (audit fix #9), mirroring the auth feature: `community.created`, `community.join_request.approved`, `community.join_request.declined`, `community.member.removed` (when added), `community.deleted`. The streak/feed `core.events` types remain separate (per §8).
- **Per-user-membership safety** is enforced by the visibility query (§3), not by client filtering. The frontend never receives data it shouldn't be able to see.

## 8. API surface — extending `app/routers/community.py`, mounted `/api/v1/community`

**Communities & membership** (new):
| Method | Path | Auth |
|---|---|---|
| `POST` | `/communities` | authed |
| `GET` | `/communities/{slug}` | authed (preview; 404 if not found) |
| `PATCH` | `/communities/{id}` | owner |
| `DELETE` | `/communities/{id}` | owner (soft-delete) |
| `POST` | `/communities/{id}/join-requests` | authed (idempotent: re-request after decline/withdraw allowed; second pending = 409) |
| `POST` | `/communities/{id}/join-requests/withdraw` | authed (the requester) |
| `GET` | `/communities/{id}/join-requests` | owner |
| `POST` | `/communities/{id}/join-requests/{req_id}/approve` | owner |
| `POST` | `/communities/{id}/join-requests/{req_id}/decline` | owner |
| `POST` | `/communities/{id}/leave` | member |
| `GET` | `/communities/mine` | authed |

**Listings** (new):
| Method | Path | Auth |
|---|---|---|
| `POST` | `/listings` | household owner/member |
| `GET` | `/listings/mine` | household owner/member/viewer (read-only) |
| `PATCH` | `/listings/{id}` | household owner/member |
| `DELETE` | `/listings/{id}` | household owner/member |
| `GET` | `/listings/{id}` | authed; visibility-gated via the helper |

**Feed** (the centerpiece):
| Method | Path | Auth |
|---|---|---|
| `GET` | `/community/feed` | authed; funnels through `listings_visible_to(...)` |

Feed query params: `community_id` (scope to one), `category` (filter on item category), `radius_miles_max` (cap distance), `cursor` / `limit` (pagination). Each row: listing data + item summary + `distance_miles` (when the radius path matched; null otherwise) + matched `community_id` (when the community path matched; null otherwise) — never the owning household's lat/lng or identity beyond what the listing carries.

**Events** emitted via `emit_event` (per `<tier>.<entity>.<action>` convention):
`community.community.created`, `community.community.deleted`, `community.member.joined`, `community.member.left`, `community.join_request.requested`, `community.join_request.approved`, `community.join_request.declined`, `community.listing.created`, `community.listing.updated`, `community.listing.removed`.

## 9. Frontend (`apps/web` additions, not rewrites)

- **`/communities`** — tabs: "My communities" (list + member counts), "Find a community" (slug input → preview → "Request to join" button; pending-request state shown).
- **`/communities/[slug]`** — detail: community description, member count; your household's listings already shared here (with quick share/unshare toggle); the feed scoped to this community; "Leave community" button. Owner-only: a "Requests" pane (list pending requests, approve/decline with optional note).
- **`/share`** — the marketplace feed. Default = combined (your communities + radius if your household has lat/lng set). Filters: community, category, max distance. Each card: item summary, lister's allowed exchange types, distance (if radius-matched), matched community (if community-matched), "View detail" (Phase 3 adds the borrow/swap/gift request button).
- **Inventory page (`/inventory`)** — each item gains: a "Shared" badge if it has any active listing; a "Share" / "Edit sharing" button that opens the listing form. The form preselects the user's communities (deselectable), exposes `share_in_radius` as an off-by-default toggle, and shows the implied visibility ("Visible to N households in: …") before submit.
- **Household location entry** — a one-time onboarding step (or settings panel) that requests browser geolocation; offers a manual lat/lng entry as a fallback for users who decline the browser permission. The UI explicitly explains who sees the location ("only households within your share radius see distance — never the exact address").
- **Sidebar** — adds a "Community" section: "Feed" → `/share`, "Communities" → `/communities`.

## 10. Migration & dependencies

- One Alembic migration `0005`: creates `community.communities`, `community.community_members`, `community.community_join_requests`, `community.listings`, `community.listing_communities`. Adds the partial unique indexes (`pending` join requests, active listing per item).
- **No new backend dependency.**
- **No new frontend dependency.** Browser geolocation is a built-in.
- `core.households.metadata_` JSONB extension is application-level — no migration.

## 11. Replacing & extending — what the test plan must include

- The existing 243-test suite continues to pass via the conftest auth override.
- **Cross-household isolation is first-class** (audit fix #15 — flagged by the Phase 1 final review):
  - Fixtures: a second seeded household + user, parameterizable in tests (a `second_household` fixture in conftest, beside the existing dev fixtures).
  - Negative tests for the visibility helper: two households, one in a shared community → sees the other's listing; one *not* in any shared community + outside radius → does NOT see the listing; one in a shared community whose lister has *left* it → does NOT see (the read-time membership check).
  - Negative test for radius: lister opts in to radius, viewer within range → sees; viewer outside range → doesn't.
  - Item soft-delete cascade test: delete an item, the listing's status becomes `removed` and stops appearing in any feed.
  - Item quantity reduction test: drops listing's `quantity_available`; drop-to-zero soft-deletes the listing.
  - Listing edit privilege test: a household member who's NOT in community X cannot add community X to a listing; can remove community X (a previous member's pick).
  - Concurrent approve test: two simultaneous approve calls on the same request — one wins (200), one loses (409).
  - User deactivation test: deactivate the lister → their listings disappear from all feeds.
  - Community soft-delete test: soft-delete a community → its `listing_communities` rows stop contributing visibility.
- Endpoint smoke tests across the whole journey: create community → request-to-join → approve → other-household creates listing → feed visibility verified end-to-end.
- Event-emission assertions for the new event types.
- A migration round-trip test for `0005`.

## 12. Out of scope (deferred)

- **Phase 3:** the borrow / swap / gift lifecycle (`community.exchanges`, the state machine, the request-to-borrow UI on a feed card). The data model here leaves clean hooks (`allowed_exchange_types`, `availability_status`).
- **Phase 4:** reputation, messaging, abuse reporting, listing ranking via LLM.
- **This spec:** community search (only slug-based discovery in v1), moderator roles beyond `owner` and `member`, OAuth / address-to-coords geocoder, rate limiting on slug enumeration, community deletion when active listings exist (v1 cascades: soft-delete the community → listings stop being visible there; v2 may show a warning).

## 13. Plan shape

One spec → one plan. Internally sequenced so cross-household isolation tests exist before the feed endpoint (which is the security-critical surface):

1. **Data model + migration 0005**, including the partial unique indexes.
2. **Service layer skeletons** — `services/community/communities.py`, `community/join_requests.py`, `community/listings.py`, `community/visibility.py`.
3. **The visibility helper itself + cross-household isolation tests** — *before* any endpoint hits it. This is the security gate; it needs proof before exposure.
4. **Communities endpoints + tests.**
5. **Join-request endpoints + tests** (including idempotency on approval).
6. **Listings endpoints + tests** (including cascade tests: item soft-delete, quantity change).
7. **Feed endpoint + tests** (the centerpiece — exercises the visibility helper end-to-end).
8. **Frontend** — auth-checked, no new dependencies.
9. **Full verification.**
