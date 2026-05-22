# Real Authentication & Multi-Household — Design Spec

**Date:** 2026-05-22
**Status:** Approved design. Next step: implementation plan via `writing-plans`.
**Type:** `core`-level feature — not tier-specific. Touches `core` schema, `app/auth.py`, the test harness, and the frontend.

---

## 1. Context & goal

The app authenticates every request as a single hardcoded dev user/household (`app/auth.py`: `seed_dev_fixtures`, `DEV_USER_ID`, `DEV_HOUSEHOLD_ID`). There is no signup, login, or session. This replaces that stub with **real custom authentication** so people have separate accounts, and completes **multi-household** support (a user may belong to several households, with one "active" per session).

This is a prerequisite for **Tier B Phase 3** (the marketplace exchange engine) — households transacting with each other is meaningless with one hardcoded household — and for every future tier with real users.

The architecture deliberately isolated this: `app/auth.py`'s two FastAPI dependencies (`get_current_user`, `get_current_household`) are the single seam. Replacing their bodies — while keeping the `CurrentUser` / `CurrentHousehold` type aliases — means **no router or service code changes**.

## 2. Scope

**In (v1):** email + password signup, login, logout; server-side sessions; in-app password change; the active-household model + a switcher; household invite-by-link; per-email login throttling.

**Deferred (design stays forward-compatible):** email verification, password reset, OAuth, MFA, IP-based throttling, CSRF tokens, a "your sessions / log out everywhere" UI, admin/role-management UI.

**Decision:** custom FastAPI auth (not Clerk/Auth.js — owning it fully); server-side sessions (not JWT); minimal v1 (no email-sending dependency).

## 3. Resolved decisions

| Topic | Decision |
|---|---|
| Session transport | httpOnly cookie holding an opaque random token. Chosen over a Bearer token for XSS resistance (JS cannot read the cookie). |
| Cookie attributes | `httpOnly`, `Path=/`, `Max-Age` = 30 days, `SameSite` and `Secure` from settings (defaults: `Lax` / off locally, on in prod). |
| Production cross-origin | `SameSite=Lax` is correct when the web app and API share a registrable domain (`hearth.com` + `api.hearth.com`). If deployed on unrelated domains, set `SameSite=None; Secure` via settings. Deploy-time decision; both are config-driven. |
| CSRF posture (v1) | Rely on `SameSite=Lax` + CORS locked to explicit origins + **all state changes are POST/PATCH/DELETE, never GET**. Deliberate, documented. CSRF tokens are a hardening follow-up. |
| Login throttling (v1) | Per-email: a failed-attempt counter on `core.users`; 5 failures → 15-minute lockout. Not IP-based (IP throttling deferred — needs a separate store). |
| Password policy | Minimum 8 characters, enforced in the Pydantic signup/password schemas. No complexity rules (length is the highest-value rule). |
| Password hashing | `bcrypt` (the `bcrypt` PyPI package) — one small, well-supported dependency. |
| Session lifetime | Fixed 30-day expiry from creation (not sliding). `last_used_at` is recorded for observability only. |
| New-signup subscription | `plan="free"`, `tier_a_enabled=True`, `tier_b_enabled=True` (Tier B Phase 1 is merged; no billing yet), `tier_s_enabled=False`. |
| Auth activity logging | signup / login / logout / password-change write a `core.audit_log` row (WHO did WHAT). Not `core.events` (that feeds streaks/feed; auth is not that). |

## 4. Data model (all in `core`)

### 4.1 New table `core.sessions`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK `core.users.id` | not null, indexed |
| `token_hash` | String(64) | `sha256(raw_token)` hex — unique, indexed. The raw token is never stored; a DB leak cannot yield live sessions. |
| `active_household_id` | UUID FK `core.households.id` | nullable |
| `expires_at` | DateTime(tz) | not null |
| `last_used_at` | DateTime(tz) | nullable — updated on each authenticated request |
| `revoked_at` | DateTime(tz) | nullable — logout / password-change sets this |
| `created_at` | DateTime(tz) | `server_default=now()` |
| `metadata_` | JSONB | user agent / IP |

A session is valid iff `revoked_at IS NULL AND expires_at > now()`.

**Deliberate deviation from inviolable rule 4 (soft delete via `deleted_at` / `TimestampMixin`):** `sessions` is ephemeral auth infrastructure, not domain data. It follows the precedent of `core.events` and `core.audit_log`, which already carry only `created_at` and no `TimestampMixin`. Logout/expiry is expressed by `revoked_at` + `expires_at`; expired rows may be hard-pruned by a future cleanup job.

### 4.2 New table `core.household_invites`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `household_id` | UUID FK `core.households.id` | not null, indexed |
| `token_hash` | String(64) | `sha256(raw_token)` hex — unique, indexed |
| `role` | String(32) | `member` or `viewer`; default `member` |
| `created_by_user_id` | UUID FK `core.users.id` | not null |
| `email` | String(320) | nullable — informational ("intended for") |
| `expires_at` | DateTime(tz) | not null (default: 7 days out) |
| `accepted_at` | DateTime(tz) | nullable |
| `accepted_by_user_id` | UUID FK `core.users.id` | nullable |
| `revoked_at` | DateTime(tz) | nullable — owner cancels an unaccepted invite |
| `created_at` | DateTime(tz) | `server_default=now()` |
| `metadata_` | JSONB | |

An invite is redeemable iff `accepted_at IS NULL AND revoked_at IS NULL AND expires_at > now()`. Same infra-table rationale as `sessions` for omitting `TimestampMixin`.

### 4.3 `core.users` — added columns

- `email_verified` Boolean, default `false` — **present but not enforced in v1** (forward-compatibility for the deferred email-verification feature).
- `failed_login_count` Integer, default `0` — reset to 0 on successful login.
- `locked_until` DateTime(tz), nullable — set when `failed_login_count` reaches 5; cleared on successful login.

`hashed_password` already exists and stays **nullable** (forward-compatibility for future OAuth-only users). `email` is already unique → the login identifier. `is_active` already exists → a deactivated user cannot log in.

### 4.4 Existing tables — unchanged

`core.households`, `core.household_members` (already has `role` = `owner|member|viewer`, `invite_email`, `invite_accepted_at`), `core.subscriptions`. The legacy `invite_email`/`invite_accepted_at` columns on `household_members` are left as-is (not used by the new invite flow, not removed — out of scope).

## 5. Auth mechanics

- **Hashing:** `bcrypt.hashpw` / `bcrypt.checkpw`.
- **Session token:** `secrets.token_urlsafe(32)`. The backend stores `sha256(token).hexdigest()` as `token_hash`; the raw token goes in the cookie. Lookups hash the cookie value and query by `token_hash`.
- **Cookie:** name `hearth_session`; `httpOnly`; `Path=/`; `Max-Age` = 30 days; `SameSite` / `Secure` from `app/config.py` settings.
- **The dependency swap** (`app/auth.py`, the whole point of the seam):
  - `get_current_user` — reads the `hearth_session` cookie, hashes it, loads a valid session, returns the `User`; updates `last_used_at`; raises `401` if the cookie is missing or the session is invalid/expired/revoked.
  - `get_current_household` — returns the `Household` referenced by the session's `active_household_id`; if null, falls back to the user's first `HouseholdMember` household and writes that back to the session; raises `401`/`400` if the user has no household.
  - `CurrentUser` / `CurrentHousehold` keep their names and types → **every existing router and service is untouched**.

## 6. Security posture (first-class section)

1. **CSRF** — v1 relies on three layers: `SameSite=Lax` cookies (a cross-site form/POST does not carry the cookie), CORS locked to explicit origins (`app/main.py` already lists `http://localhost:3000` with `allow_credentials=True`), and the invariant that **no endpoint mutates state on a GET**. This is the documented v1 posture. Synchronizer CSRF tokens are a deferred hardening step.
2. **Brute force** — per-email throttling (§3). `bcrypt`'s deliberate slowness is an additional cost on each attempt. A locked account returns `429` until `locked_until`.
3. **Token handling** — only the SHA-256 hash of a session/invite token is persisted; raw tokens exist only in the cookie / invite URL.
4. **Password change revokes other sessions** — `POST /auth/password` sets `revoked_at` on all of the user's *other* sessions (keeps the current one), limiting the blast radius of a compromised password.
5. **Enumeration** — login returns the same `401` for unknown-email and wrong-password. Signup necessarily reveals email-in-use via `409` (accepted tradeoff for a clear signup UX).

## 7. API surface — new `app/routers/auth.py`, mounted `/api/v1/auth`

| Method & path | Auth required | Behavior |
|---|---|---|
| `POST /signup` | public | Body `{email, password, display_name, household_name}`. Creates `User` (bcrypt hash), `Household`, `HouseholdMember(owner)`, `Subscription` (§3). Opens a session, sets the cookie, writes `audit_log`. `409` on duplicate email (catch the unique-constraint `IntegrityError`). Returns `{user, household}`. |
| `POST /login` | public | Body `{email, password}`. Applies throttling. On success: reset `failed_login_count`, open session, set cookie, `audit_log`. `401` bad credentials, `429` locked. |
| `POST /logout` | authed | Revokes the current session (`revoked_at = now`), clears the cookie, `audit_log`. |
| `GET /me` | authed | Returns `{user, memberships: [{household, role}], active_household}` — frontend bootstrap. |
| `POST /password` | authed | Body `{current_password, new_password}`. Verifies current; updates hash; revokes the user's other sessions; `audit_log`. |
| `POST /households` | authed | Body `{name}`. Creates a `Household` + `HouseholdMember(owner)`; the caller may then switch to it. |
| `POST /switch-household` | authed | Body `{household_id}`. `403` unless the user is a member; sets the session's `active_household_id`. |
| `POST /households/{id}/invites` | authed, **owner of {id}** | Body `{role, email?}`. Mints an invite; returns `{token, url, expires_at}`. `403` if not an owner. |
| `DELETE /households/{id}/invites/{invite_id}` | authed, **owner of {id}** | Sets `revoked_at`. |
| `GET /invites/{token}` | authed | Preview: `{household_name, role, inviter_name}`. `410` if not redeemable. |
| `POST /invites/{token}/accept` | authed | Creates a `HouseholdMember` with the invite's role; sets `accepted_at` / `accepted_by_user_id`. `410` if expired/revoked/already accepted. |

**Authorization summary:** `signup`/`login` are public; everything else requires a valid session; `create-invite` and `revoke-invite` additionally require the caller to be an `owner` of that household; `switch-household` requires membership of the target.

## 8. Multi-household & active household

- A user belongs to many households via `core.household_members`. Each **session** carries one `active_household_id` — so the "current household" is per-device, and switching on one device doesn't disturb another.
- On signup the user gets one household (becomes its `owner`); the session's `active_household_id` is set to it.
- Additional households arrive two ways: `POST /households` (create your own) or accepting an invite (`POST /invites/{token}/accept`).
- `get_current_household` resolves the session's `active_household_id`; every existing tier query (`WHERE household_id = current_household.id`) then becomes genuine multi-tenant isolation with no code change.

## 9. Replacing the dev stub + the test strategy

### 9.1 Stub replacement
`seed_dev_fixtures` is split:
- `seed_reference_data()` — starter ingredients + badge definitions (global, not user-specific) — **keeps running on app startup** (`app/main.py` lifespan).
- The dev user/household/subscription/membership auto-seed is **removed from startup**. A fresh dev database has no users; you sign up through the UI.
- A helper script `apps/backend/scripts/create_user.py` creates a user from the command line (for local dev / seeding), and can optionally adopt the legacy `DEV_HOUSEHOLD_ID` household so existing local Tier A data stays reachable.

### 9.2 The 213-existing-tests strategy (zero test-file changes)
- `DEV_USER_ID` / `DEV_HOUSEHOLD_ID` **stay as constants in `app/auth.py`** (stable UUIDs). ~30 test files import them; keeping them there means those imports keep resolving.
- `tests/conftest.py`'s session fixture seeds the test `User` + `Household` + `HouseholdMember` + `Subscription` using those exact IDs (the old dev seeding, relocated from app startup into the test harness) and calls `seed_reference_data()`.
- An **autouse** conftest fixture installs `app.dependency_overrides[get_current_user]` and `[get_current_household]` to return the test fixtures — so every endpoint test resolves to the test household exactly as before.
- Result: all 213 existing tests pass **unchanged** — HTTP tests via the override, service tests via `db.get(Household, DEV_HOUSEHOLD_ID)`, and the existing `_clean_household_data` cleanup keyed on `DEV_HOUSEHOLD_ID`.
- **Auth-flow tests opt out:** tests marked `@pytest.mark.real_auth` get no dependency override (the autouse fixture checks the marker and skips). The rewritten `tests/test_auth.py` uses that marker to exercise the real signup → cookie → session → login → logout → password → switch → invite flow end to end.

## 10. Frontend (`apps/web`)

- **New pages:** `/login`, `/signup`, and `/invite/[token]` (preview + accept; if unauthenticated, redirect to `/signup?return=/invite/<token>`).
- **`api()` helper** (`src/lib/api.ts`) gains `credentials: "include"` so the cookie is sent on every call; a `401` is surfaced distinctly so the guard can react.
- **Auth guard:** a client component (consistent with the all-`"use client"` codebase) wraps the app shell — on mount it calls `GET /auth/me`; a `401` redirects to `/login`. The guard is inert on `/login` and `/signup`.
- **`Sidebar.tsx`** — the footer's hardcoded "Dev Household" becomes the real active household name + a switcher dropdown (lists memberships, calls `POST /switch-household`, reloads) + a logout button.
- **`ChatSidebar.tsx`** — conversation state resets when the active household changes (conversations are household-scoped); add the active household to the existing reset effect's dependencies.
- New `lib/api.ts` functions + `lib/types.ts` types for: `signup`, `login`, `logout`, `getMe`, `changePassword`, `createHousehold`, `switchHousehold`, `previewInvite`, `acceptInvite`, `createInvite`, `revokeInvite`.

## 11. Migration & dependency

- One Alembic migration `0004` (`down_revision = "0003"` — `0003` is the latest revision, from the merged Tier B work): creates `core.sessions` and `core.household_invites`; adds `email_verified`, `failed_login_count`, `locked_until` to `core.users`.
- New backend dependency: `bcrypt`.

## 12. Testing

- Rewritten `tests/test_auth.py` (`@pytest.mark.real_auth`): signup (incl. duplicate-email `409`), login (success, bad creds `401`, lockout `429` after 5 failures), logout (session revoked), `GET /me`, password change (+ other sessions revoked), create household, switch household (+ `403` for non-member), invite create/preview/accept/revoke (+ `410` on expired/revoked/accepted).
- `conftest.py` changes per §9.2.
- A migration round-trip test for `0004`.
- The full suite (the existing 213 + the new auth tests) must pass.

## 13. Out of scope / deferred

Email verification, password reset, OAuth, MFA, IP-based rate limiting, synchronizer CSRF tokens, a sessions-management UI, and admin/role-management UI. The data model is left forward-compatible (`email_verified` column present; sessions revocable per-user).

## 14. Roadmap update

The Tier B roadmap (`docs/superpowers/specs/2026-05-21-tier-b-community-marketplace-design.md`) will gain a **"Prerequisite: real authentication"** note recording that Phase 3 (Exchange Engine) is gated on this work, with a pointer to this spec.

## 15. Plan shape

This is one cohesive feature (the layers are not independently shippable), so it is one spec → one plan. The implementation plan will be **internally sequenced**: (1) data model + migration + `bcrypt`; (2) auth mechanics + the `auth.py` dependency swap + the conftest test strategy; (3) the auth API surface; (4) multi-household + invites; (5) frontend; (6) full verification — so the 213-test safety net is re-established as early as step 2.
