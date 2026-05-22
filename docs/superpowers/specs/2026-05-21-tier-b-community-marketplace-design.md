# Tier B — Community Marketplace: Roadmap & Coexistence Design

**Date:** 2026-05-21
**Status:** Approved roadmap. Each phase below gets its own brainstorm → spec → plan cycle.
**Scope:** This is a *decomposition + architecture* spec, not a single implementation plan. It establishes the phases, the exchange/community model, and how single-household and multi-household features coexist. Phase 1 is brainstormed next as its own spec.

---

## 1. Context

The product expands from single-household frugality tools (Tier A food) into a **hyperlocal community marketplace**: households catalog what they own and lend / swap / give items to other households nearby. This was always the plan — `ARCHITECTURE.md` reserves **Tier B — Community** ("hyperlocal sharing, skill barter, mending, library aggregation") with a `community` schema slot. This spec fills that slot.

The frugal thesis holds: borrowing a drill you'd use twice a year, instead of buying one, is money not spent — and that flows into the existing savings dashboard.

## 2. Decisions locked

| Decision | Choice | Consequence |
|---|---|---|
| **Exchange model** | Borrow/lend, swap, and gift. **No selling.** | No payments dependency; `ARCHITECTURE.md`'s "no payments" non-goal holds. |
| **Community model** | Hybrid: explicit groups you join **and** geographic radius. | Needs both a groups model and household location; doubles discovery logic. |
| **Sequencing** | Bring Tier B forward, **ahead of Tier S (Bills)**. | No Tier S work has started; `tier_b_enabled` already gates it independently; a sharing marketplace has network effects that help a pre-launch product more than a bill auditor. |
| **Build approach** | Vertical slices — 4 phases, each independently shippable. | Matches "expand slowly"; no half-built subsystems carried between phases. |

## 3. The one big architectural shift

Every tier so far is **single-household** — every query is `WHERE household_id = me`. Tier B is the first tier where households **see and transact with each other**. The inventory CRUD is easy; the design weight is in four things the current architecture does not yet handle, each assigned to the phase that first needs it:

1. **Multi-household visibility** — a new access pattern: "listings visible to me" (my groups ∪ my radius), not "rows I own." → Phase 2
2. **Geo queries** — radius search. Use plain bounding-box math on lat/long float columns; no PostGIS/earthdistance extension (a new extension needs human sign-off per the inviolable rules, and bounding-box is sufficient at pre-launch scale). → Phase 2
3. **Cross-household events** — `core.events` has a single `household_id`; an exchange involves two. → Phase 3 (see §5.2)
4. **Notifications** — a borrow request must reach the owner; today the only push surface is the daily briefing. → Phase 3

## 4. The roadmap

### Phase 1 — Household Inventory
Single-household, zero marketplace. Catalog what you own beyond the food pantry (games, tools, books).
- **Tables:** `community.items`, optional `community.item_locations` (mirrors `food.pantry_locations`).
- **LLM:** `extract_items_from_image` — reuses the exact vision pattern as `extract_pantry_from_image`. Snap a shelf of board games → structured items.
- **Events:** `community.item.{added,updated,removed}`.
- **Frontend:** `/inventory`.
- **Why first:** independently valuable ("know what you own, stop re-buying") and carries zero multi-household risk.

### Phase 2 — Community & Shareable Listings
- **Geography:** add household lat/long. Start in `core.households.metadata_` (Rule 3 — JSONB until a field is hot); promote to indexed columns when radius queries prove hot.
- **Tables:** `community.communities`, `community.community_members` (invite code / request-to-join, roles); `community.listings`.
- **Key separation:** an `item` is private inventory; a `listing` is its public, shareable projection (allowed exchange types + group/radius visibility + availability). Inventory stays private by default — items are opted into sharing.
- **New pattern:** `services/community/visibility.py` — the single canonical "listings visible to household X" query (see §5.3).
- **Endpoints:** community join/CRUD, listing CRUD, `GET /community/feed` (the hybrid discovery query).
- **Events:** `community.community.created`, `community.member.joined`, `community.listing.created`.
- Multi-household *reads* appear here; no transactions yet.

### Phase 3 — Exchange Engine
The borrow / swap / gift lifecycle — the heaviest phase.
- **Table:** `community.exchanges` with a per-type state machine:
  - **borrow:** `requested → accepted → handed_over → returned` (+ `overdue`, `declined`, `cancelled`)
  - **swap:** `proposed → countered → accepted → completed`
  - **gift:** `claimed → handed_over → completed`
- **Overdue detection:** piggyback the overdue sweep on the existing 7am briefing job — no background queue is introduced.
- **Cross-household events:** emit two events per cross-household action (see §5.2).
- **Tracking payoff:** a completed borrow = money not spent → `tracking.savings_events` with `kind = 'borrowed_not_bought'`; a completed gift/swap receipt → `gift_received` / the existing `swap_received`. Flows through the existing event→tracking subscriber pattern — no new coupling.
- **AI:** `ai.conversations` gains `scope = 'community'` — "find me a tent to borrow nearby."

### Phase 4 — Trust Layer
- **Reputation:** post-exchange ratings, completion rate, on-time-return rate — a materialized rollup like `tracking.streaks`.
- **Messaging:** lightweight listing/exchange-scoped threads between households.
- **Feed ranking:** reuses the already-stubbed `rank_content_for_household` idea as `rank_listings_for_household`.
- **Safety:** reporting and blocking.

## 5. Coexistence: how single-household and community share one app

**Verdict:** they coexist cleanly because **the marketplace's unit of ownership is still the household.** A listing is owned by a household; an exchange happens between two households. Tier B introduces no new kind of actor and does not change how Tier A works.

### 5.1 What is already right (no change needed)
- **`core` already models "an org and its members."** `HouseholdMember` has owner/member/viewer roles and many-users-per-household. Each side of a marketplace transaction is exactly that. `household_id` = the owning party; `user_id` on events = who acted.
- **`food.recipes` is a precedent** for a shared, non-household-scoped table inside a tier schema (it has no `household_id`, only `created_by_user_id`). Tier B `listings` extend that established pattern.
- **Cross-cutting modules were built anticipating Tier B:**
  - `ai.conversations.scope` already lists `community` as a legal value.
  - `tracking.savings_events.kind` already lists `swap_received`; its docstring says *"Tier B: shared goods received."* New kinds are data, not migrations.
  - `content.items.topic` already routes to any tier.

### 5.2 The one real gap — `core.events` single `household_id`
`Event` has exactly one nullable `household_id`, but an exchange concerns two households. A borrow event logged with only the borrower's id is invisible to the lender's `WHERE household_id = me` briefing/streak queries.

**Decision: emit two events for cross-household actions** — same `event_type`, same `entity_id` (the exchange), one row per involved household, `payload.role = lender|borrower`. Zero schema change; keeps the `idx_events_household` index; every existing consumer keeps working untouched. Add one helper to `services/events.py`:

```python
def emit_event_for_households(db, *, event_type, household_ids, role_by_household, ...):
    """Emit one core.events row per involved household for a cross-household action."""
```

Rejected alternatives: stashing `counterparty_household_id` in `payload` (forces JSONB scans, bypasses the index); adding a `counterparty_household_id` column to `core.events` (a core schema change that skirts inviolable Rule 2).

### 5.3 The latent risk — scoping is per-route convention, not enforced
Every Tier A query hand-writes `WHERE household_id == household.id`; ownership re-checks are ad hoc (`mark_shopping_item_purchased` re-verifies via the parent list; `update_planned_meal_status` checks `pm.meal_plan.household_id`). Fine for one tenant filter. But Tier B has **four overlapping visibility rules**: items I own ∪ listings shared to my groups ∪ listings in my radius ∪ exchanges I'm a party to. Hand-rolling that per endpoint will eventually leak other households' data.

**Decision:** Tier B introduces one new pattern — `services/community/visibility.py`, the single canonical "listings/exchanges visible to household X" query, reused by every community read endpoint. **Do not retrofit Tier A** (it is correct as-is); just establish the helper for Tier B so the marketplace's access logic lives in exactly one place.

### 5.4 Net effect on `core`
| Concern | Change required | Phase |
|---|---|---|
| Actor model (household = party) | None — already fits | — |
| `ai` / `tracking` / `content` extension | Data only (new enum values) | 2–4 |
| `core.events` two-household | One helper fn, **no migration** | 3 |
| Visibility helper (new pattern) | New `services/community/visibility.py` | 2 |
| Household location | `metadata_` → indexed columns later | 2 |

Tier B touches `core` exactly once, and it is a helper function — not a schema change.

## 6. `community` schema sketch

Per-phase; each table follows the inviolable rules (own schema, `metadata_` JSONB, `deleted_at` soft delete, FK only into `core`).

```
community/                              Tier B
  items                  (P1) household-owned possession; FK core.households
  item_locations         (P1, optional) where an item is stored
  communities            (P2) a joinable group (building, street, friend circle)
  community_members      (P2) household ↔ community join; role, invite/join state
  listings               (P2) public shareable projection of an item;
                              allowed exchange types, visibility, availability
  exchanges              (P3) borrow/swap/gift lifecycle; lender + borrower
                              household FKs, type-specific state machine
  reputation             (P4) materialized per-household trust rollup
  messages               (P4) listing/exchange-scoped household-to-household threads
  reports                (P4) abuse reports
```

`core.households` gains lat/long (Phase 2; `metadata_` first, columns when hot).

## 7. New event types

Following the `<tier>.<entity>.<action>` convention enforced by `services/events.py`:

- Phase 1: `community.item.added`, `community.item.updated`, `community.item.removed`
- Phase 2: `community.community.created`, `community.member.joined`, `community.listing.created`
- Phase 3: `community.exchange.requested`, `community.exchange.accepted`, `community.exchange.completed`, `community.exchange.overdue` (cross-household ones emitted twice — see §5.2)
- Phase 4: `community.exchange.rated`, `community.report.filed`

## 8. Open questions for the Phase 1 brainstorm

Deferred to the Phase 1 (Inventory) design, not decided here:
- Inventory taxonomy — fixed category enum vs. free-form tags.
- Whether Phase 1 needs `item_locations` on day one or it lands with listings.
- Item identity — per-unit rows vs. quantity on one row (board games are unit-ish; "8 folding chairs" is quantity-ish).
- Photo capture UX — one item per photo vs. batch shelf extraction.

## 9. Next step

Brainstorm **Phase 1 — Household Inventory** as its own design spec, then a `writing-plans` implementation plan for it. Phases 2–4 are brainstormed when their turn comes.
