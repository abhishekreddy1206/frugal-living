# Admin Console, App Settings, and Feature Flags — Design Spec

**Date:** 2026-05-24
**Status:** Approved scope; ready for implementation plan.
**Builds on:** Phase 1.5 real auth (`docs/superpowers/specs/2026-05-22-real-auth-multi-household-design.md`), Tier B Phase 2 listings (`docs/superpowers/specs/2026-05-24-tier-b-phase-2-community-listings-design.md`).

---

## 1. Context

After Phase 2 shipped, the platform has real users, real communities, and real public listings — but the operator has no way to administer any of it. There is no admin account, no DB-backed app settings, and the `core.feature_flags` table is defined but unused. With public listings live, there is also no moderation surface.

This spec adds three intertwined capabilities:

1. **Three-role access model** — `user`, `moderator`, `admin` — with a seeded admin bootstrap and audit-logged role changes.
2. **App settings** — a Python registry + 3-layer JSONB storage (global / household / user) with a typed resolver.
3. **Feature flags** — wires the existing `core.feature_flags` table to a service, adds per-household / per-user overrides on top of the existing `enabled_globally` + `rollout_percent`.
4. **Admin console** — backend endpoints + Next.js `/admin/*` pages, role-gated, with a dedicated moderation surface for taking down communities, listings, and abusive users.

The whole thing fits into `core` (it's tier-agnostic infrastructure). No tier-specific code is touched; the moderation surface operates on Phase 2 community tables only because that's the only tier with public, multi-household content today.

## 2. Decisions locked (from brainstorming)

| Decision | Choice | Implication |
|---|---|---|
| Admin model | Multi-admin via `User.role` column | DB-level role enum; promote/demote endpoints; first admin seeded via env vars. |
| Settings scope | Global + household + user (three layers) | Three storage tables; resolver picks user → household → global → registry default. |
| Settings shape | Python registry + JSONB storage at every layer | Adding a setting is code-only; no migration. Types declared in the registry, checked on read/write. |
| Admin UI scope | Full admin console (backend + frontend) | New `/admin/*` Next.js routes + sidebar gating. |
| Moderation | Third role `moderator`; takes down listings/communities/users; cannot touch settings/flags | Two auth dependencies (`require_admin`, `require_moderator`); page- and endpoint-level gating. |

## 3. Adherence to the 7 inviolable rules

- **Rule 1 (schema namespacing per tier):** Everything in this spec lives in `core`. The settings tables, feature-flag overrides, role column, and all routers are tier-agnostic. ✓
- **Rule 2 (core stays tier-agnostic):** No tier-specific columns or references. The moderation surface acts on Tier B community tables but the moderation code lives in `routers/admin.py` and uses generic types. ✓
- **Rule 3 (`metadata_` JSONB on every domain table):** All new tables include it. The settings tables themselves *are* JSONB key/value storage, so `metadata_` is redundant on those — documented inline. ✓ (with explicit exception)
- **Rule 4 (soft delete via `deleted_at`):** Settings rows and feature-flag overrides are *configuration*, not domain data. They follow the same "deliberate deviation" pattern as `core.sessions` and `core.audit_log`: lifecycle is "set" / "unset" via DELETE, history lives in `core.audit_log`. Documented inline. ✓ (with explicit exception)
- **Rule 5 (emit events for mutations):** Admin and moderator actions emit to `core.events` with namespaced types (`admin.user.role_changed`, `admin.listing.taken_down`, etc.) **and** to `core.audit_log` (the latter is the authoritative who/what/why ledger). ✓
- **Rule 6 (single subscription, multi-tier flags):** Untouched. Subscriptions and tier flags are unrelated to admin/moderator status. ✓
- **Rule 7 (LLM calls via `services/llm.py`):** This spec adds zero LLM calls. ✓

## 4. Role model

### 4.1 Schema change

Single column added to `core.users`:

```python
role: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
# "user" | "moderator" | "admin"
```

Plus a DB-level CHECK constraint so typos can't produce an unknown role:

```sql
ALTER TABLE core.users
  ADD CONSTRAINT users_role_valid CHECK (role IN ('user', 'moderator', 'admin'));
```

Migration `0006_admin_role.py`: adds the column with default `'user'`, backfills all existing rows to `'user'`, adds the CHECK.

### 4.2 Permission helpers

New module `apps/backend/app/services/auth/permissions.py`:

```python
from app.models.core import User

def is_admin(u: User) -> bool:
    return u.role == "admin" and u.is_active

def is_moderator(u: User) -> bool:
    return u.role == "moderator" and u.is_active

def is_at_least_moderator(u: User) -> bool:
    return u.role in ("admin", "moderator") and u.is_active
```

Pure functions, no I/O. Reused in dependencies, route bodies, and tests.

### 4.3 Auth dependencies

Added to `app/auth.py` alongside the existing `get_current_user` / `get_current_household`:

```python
def require_admin(user: CurrentUser) -> User:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="admin required")
    return user

def require_moderator(user: CurrentUser) -> User:
    """Pass if user is admin OR moderator. Used for moderation endpoints."""
    if not is_at_least_moderator(user):
        raise HTTPException(status_code=403, detail="moderator required")
    return user

CurrentAdmin     = Annotated[User, Depends(require_admin)]
CurrentModerator = Annotated[User, Depends(require_moderator)]
```

`get_current_user` already returns 401 when no session — these only need 403 (authenticated, not authorized).

### 4.4 Last-admin guard

A single helper, used by every admin-status-changing operation:

```python
def assert_not_last_admin(db: DbSession, target_user: User) -> None:
    """Block role-change-away-from-admin or deactivation of the last admin."""
    if target_user.role != "admin":
        return
    other_admins = (
        db.query(User)
        .filter(User.id != target_user.id, User.role == "admin", User.is_active.is_(True))
        .count()
    )
    if other_admins == 0:
        raise HTTPException(status_code=400, detail="cannot remove the last active admin")
```

Called from `PATCH /admin/users/{id}` whenever the target is currently an admin and the change would either (a) reduce their role or (b) set `is_active=False`.

## 5. Admin bootstrap

### 5.1 Env vars

Added to `app/config.py`:

```python
admin_email:         str | None = None    # set in .env to enable bootstrap
admin_password:      str | None = None    # bcrypt-hashed only at bootstrap; cleared from process memory after
admin_display_name:  str | None = None    # optional; defaults to email local-part
```

`.env.example` updated; `.env` is local-only (already in `.gitignore`).

### 5.2 Bootstrap flow

New `apps/backend/app/services/admin/bootstrap.py`:

```python
def bootstrap_admin(db: DbSession, *, email: str, password: str, display_name: str | None) -> None:
    """Idempotent: create the bootstrap admin if missing; ensure role=admin if present.
    NEVER overwrites an existing password — rotate via POST /auth/password.
    """
```

1. If `email` not set → no-op (production hardening: explicit opt-in via env var).
2. Look up `User` by email.
3. **If missing:**
   - Create `User(email=email, hashed_password=bcrypt(password), display_name=…, role="admin", is_active=True, email_verified=True)`.
   - Create a personal `Household(name="<display_name>'s Household")`.
   - Wire `HouseholdMember(role="owner")`.
   - Write `AuditLog(action="admin.bootstrap.created", target_user=…)`.
4. **If exists:**
   - If `role != "admin"` → set `role="admin"`, write `AuditLog(action="admin.bootstrap.promoted")`.
   - Never touch the password.
5. Wired into `seed_reference_data()` in `app/auth.py`, so it runs on every startup (idempotent).

### 5.3 No moderator bootstrap

Moderators are real humans admins promote *after* the human signs up normally. There is no `MODERATOR_EMAIL` env var. This keeps the env surface minimal and forces moderator admission through the audited promote endpoint.

## 6. App settings

### 6.1 Registry

New module `apps/backend/app/services/settings/registry.py`:

```python
from dataclasses import dataclass
from typing import Any

Scope = str  # "global" | "household" | "user"

@dataclass(frozen=True)
class SettingSpec:
    type: type                  # bool | int | str | float
    default: Any                # must be an instance of `type`
    scopes: tuple[Scope, ...]   # which layers may set this key
    description: str
    public: bool = False        # exposed via /api/v1/runtime-config (no auth)

SETTING_REGISTRY: dict[str, SettingSpec] = {
    # --- Operator-only globals ---
    "signups_open":            SettingSpec(bool, True,    ("global",),
        "Allow new account signups", public=True),
    "maintenance_message":     SettingSpec(str,  "",      ("global",),
        "Public banner shown across all pages; empty = no banner", public=True),
    "llm_cli_concurrency":     SettingSpec(int,  4,       ("global",),
        "Max in-flight Claude CLI subprocess calls"),

    # --- Cascadable defaults ---
    "default_ai_model":        SettingSpec(str,  "sonnet",("global", "household"),
        "Default Claude model for new AI calls"),
    "briefing_hour_local":     SettingSpec(int,  7,       ("global", "household", "user"),
        "Local hour (0-23) when daily briefings are generated"),
    "pantry_expiry_warn_days": SettingSpec(int,  3,       ("global", "household"),
        "Warn N days before pantry items expire"),

    # --- User-only preferences ---
    "theme":                   SettingSpec(str,  "warm",  ("user",),
        "UI theme: 'warm' | 'muted'"),
    "email_notifications":     SettingSpec(bool, True,    ("user",),
        "Receive email notifications"),
}
```

Adding a new setting = one entry in this dict. No migration. The frontend reads the registry shape via `GET /admin/settings/registry` (admin only) so its UI widgets stay in sync automatically.

### 6.2 Storage — three new tables

All in `core` schema. Migration `0007_app_settings.py`.

```sql
CREATE TABLE core.app_settings_kv (
  key                 VARCHAR(120) PRIMARY KEY,
  value               JSONB NOT NULL,
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_by_user_id  UUID REFERENCES core.users(id)
);

CREATE TABLE core.household_settings (
  household_id        UUID NOT NULL REFERENCES core.households(id),
  key                 VARCHAR(120) NOT NULL,
  value               JSONB NOT NULL,
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_by_user_id  UUID REFERENCES core.users(id),
  PRIMARY KEY (household_id, key)
);

CREATE TABLE core.user_settings (
  user_id     UUID NOT NULL REFERENCES core.users(id),
  key         VARCHAR(120) NOT NULL,
  value       JSONB NOT NULL,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_id, key)
);
```

**Rule 3 / Rule 4 deviations** documented in the model files:
- These tables *are* key/value JSONB — `metadata_` would be redundant.
- Soft delete makes no sense for "setting cleared"; DELETE returns the key to the registry default. History lives in `core.audit_log`.

### 6.3 Resolver

`apps/backend/app/services/settings/resolver.py`:

```python
def get_setting(
    db: DbSession,
    key: str,
    *,
    user: User | None = None,
    household: Household | None = None,
) -> Any:
    spec = SETTING_REGISTRY[key]            # raises KeyError on programmer typo
    if user and "user" in spec.scopes:
        row = db.get(UserSetting, (user.id, key))
        if row is not None:
            return _coerce(row.value, spec, key=key)
    if household and "household" in spec.scopes:
        row = db.get(HouseholdSetting, (household.id, key))
        if row is not None:
            return _coerce(row.value, spec, key=key)
    row = db.get(AppSettingKv, key)
    if row is not None:
        return _coerce(row.value, spec, key=key)
    return spec.default


def _coerce(value: Any, spec: SettingSpec, *, key: str) -> Any:
    """Type-check JSONB-decoded value against spec.type. Log + return default on mismatch."""
    if isinstance(value, spec.type) and not (spec.type is int and isinstance(value, bool)):
        # bool is a subclass of int in Python; reject bool-where-int-expected explicitly
        return value
    logger.warning(
        "setting %s has type %s, expected %s; falling back to default",
        key, type(value).__name__, spec.type.__name__,
    )
    return spec.default


def set_setting(
    db: DbSession,
    key: str,
    value: Any,
    *,
    scope: Scope,
    scope_id: uuid.UUID | None,
    actor: User,
) -> None:
    spec = SETTING_REGISTRY[key]
    if scope not in spec.scopes:
        raise ValueError(f"{key} is not overridable at {scope} scope")
    if not isinstance(value, spec.type) or (spec.type is int and isinstance(value, bool)):
        raise ValueError(f"{key} expects {spec.type.__name__}")
    # upsert into the right table, write audit log entry, no commit (caller controls tx)
```

Caching is deliberately not added — measure first. JSONB lookups by PK are cheap.

### 6.4 Endpoints

**Admin (`require_admin`):**
```
GET    /api/v1/admin/settings                                — list registry + current globals + override counts
GET    /api/v1/admin/settings/registry                       — raw registry (for UI widget generation)
GET    /api/v1/admin/settings/{key}                          — global + all household overrides + all user overrides (paginated)
PUT    /api/v1/admin/settings/{key}                          — set/replace global; body { value }
DELETE /api/v1/admin/settings/{key}                          — clear global (returns to registry default)
PUT    /api/v1/admin/settings/{key}/household/{hid}          — set/replace household override
DELETE /api/v1/admin/settings/{key}/household/{hid}          — clear household override
PUT    /api/v1/admin/settings/{key}/user/{uid}               — set/replace user override
DELETE /api/v1/admin/settings/{key}/user/{uid}               — clear user override
```

**Self-service (regular `CurrentUser`):**
```
GET    /api/v1/me/settings                                   — my user-scoped settings (keys with "user" in scopes)
PUT    /api/v1/me/settings/{key}                             — set my user-scoped setting
DELETE /api/v1/me/settings/{key}                             — clear my user override

GET    /api/v1/households/{hid}/settings                     — household-scoped (member-readable)
PUT    /api/v1/households/{hid}/settings/{key}               — owner role only (reuses _require_owner from auth router)
DELETE /api/v1/households/{hid}/settings/{key}               — owner role only
```

**Public (no auth):**
```
GET    /api/v1/runtime-config                                — returns only keys with public=True
```

Used by the frontend before login to render the maintenance banner and gate the "Sign up" CTA against `signups_open`.

## 7. Feature flags

### 7.1 Existing `core.feature_flags` (no schema change)

Already shipped in `0002_create_all_tables.py`. Untouched. Has `key`, `description`, `enabled_globally`, `rollout_percent`, `metadata_`, `deleted_at`.

### 7.2 New `core.feature_flag_overrides` table

Migration `0007_app_settings.py` (same migration as settings — they ship together).

```sql
CREATE TABLE core.feature_flag_overrides (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  flag_key            VARCHAR(120) NOT NULL REFERENCES core.feature_flags(key) ON DELETE CASCADE,
  household_id        UUID REFERENCES core.households(id),
  user_id             UUID REFERENCES core.users(id),
  enabled             BOOLEAN NOT NULL,
  created_by_user_id  UUID REFERENCES core.users(id),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK ((household_id IS NULL) <> (user_id IS NULL))  -- XOR: exactly one
);

CREATE UNIQUE INDEX ux_flag_override_household
  ON core.feature_flag_overrides (flag_key, household_id)
  WHERE user_id IS NULL;

CREATE UNIQUE INDEX ux_flag_override_user
  ON core.feature_flag_overrides (flag_key, user_id)
  WHERE household_id IS NULL;
```

Same Rule-4 deviation as settings (configuration, not domain data; lifecycle is via DELETE).

`flag_key` is a varchar FK to `feature_flags.key` (which is unique). Cascade on delete handles flag removal cleanly.

### 7.3 Resolver

`apps/backend/app/services/flags/resolver.py`:

```python
import hashlib

def is_enabled(
    db: DbSession,
    key: str,
    *,
    user: User | None = None,
    household: Household | None = None,
) -> bool:
    flag = (
        db.query(FeatureFlag)
        .filter(FeatureFlag.key == key, FeatureFlag.deleted_at.is_(None))
        .first()
    )
    if flag is None:
        return False                                      # unknown / deleted flag = off

    # 1. User override (highest priority)
    if user:
        ov = (
            db.query(FeatureFlagOverride)
            .filter_by(flag_key=key, user_id=user.id)
            .first()
        )
        if ov is not None:
            return ov.enabled

    # 2. Household override
    if household:
        ov = (
            db.query(FeatureFlagOverride)
            .filter_by(flag_key=key, household_id=household.id)
            .first()
        )
        if ov is not None:
            return ov.enabled

    # 3. Global
    if flag.enabled_globally:
        return True

    # 4. Rollout percent (requires a stable user identity)
    if flag.rollout_percent > 0 and user is not None:
        h = int(hashlib.sha256(f"{key}:{user.id}".encode()).hexdigest()[:8], 16)
        return (h % 100) < flag.rollout_percent

    return False
```

**Hash properties:** keyed on `(flag_key, user_id)` so different flags rotate through different cohorts — a user isn't always in or always out across every flag. Same user always gets the same answer for the same flag (consistent ramp).

**Pre-login behavior:** no user → rollout percent is ignored. Only `enabled_globally` applies. Anonymous routes effectively see a binary global flag.

### 7.4 Endpoints

**Admin (`require_admin`):**
```
GET    /api/v1/admin/flags                              — list (with override counts per flag)
GET    /api/v1/admin/flags/{key}                        — detail + all overrides
POST   /api/v1/admin/flags                              — create; body { key, description, enabled_globally?, rollout_percent? }
PATCH  /api/v1/admin/flags/{key}                        — partial update (description, enabled_globally, rollout_percent)
DELETE /api/v1/admin/flags/{key}                        — soft-delete (sets deleted_at; resolver then returns False, making overrides moot — they are NOT auto-removed)
PUT    /api/v1/admin/flags/{key}/household/{hid}        — set/replace household override; body { enabled }
DELETE /api/v1/admin/flags/{key}/household/{hid}        — clear household override
PUT    /api/v1/admin/flags/{key}/user/{uid}             — set/replace user override
DELETE /api/v1/admin/flags/{key}/user/{uid}             — clear user override
```

### 7.5 Initial seeded flags

Added to `seed_reference_data()` via `INSERT … ON CONFLICT (key) DO NOTHING`:

| key | initial state | purpose |
|---|---|---|
| `community.exchange_engine.enabled` | off | Phase 3 dark launch |
| `ai.opus_meal_planner.enabled`      | on  | Kill-switch if costs spike |
| `content.youtube_ingestion.enabled` | on  | Kill-switch |
| `voice.assistant.enabled`           | off | Voice routes are stubs today; flag is the eventual launch gate |

No callers added in this spec. Each tier opts in by calling `is_enabled(key, user, household)` from its own services when it wants to.

## 8. Moderation surface

The operational tools that make the moderator role useful. All endpoints under `/api/v1/admin/*`, all use `require_moderator`, all writes require a non-empty `reason` field that lands in `core.audit_log.payload.reason`.

### 8.1 Required `reason` field

A small Pydantic helper:

```python
class ModerationReason(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)
```

Every moderator-write request body extends this. Empty / whitespace-only → 422 (Pydantic). The reason is persisted to:
- `core.audit_log.payload.reason` (always)
- `core.events.payload.reason` (when an event is also emitted)

### 8.2 Endpoints

```
# --- Communities ---
GET    /api/v1/admin/communities                          — paginated, search, filter by deleted
GET    /api/v1/admin/communities/{id}                     — detail + member list + listing count + creator
POST   /api/v1/admin/communities/{id}/take-down           — soft-delete (deleted_at=NOW); body { reason }
POST   /api/v1/admin/communities/{id}/restore             — clear deleted_at; body { reason }

# --- Listings ---
GET    /api/v1/admin/listings                             — paginated, search, filter by availability_status
GET    /api/v1/admin/listings/{id}                        — detail + owner + visibility scope + community memberships
POST   /api/v1/admin/listings/{id}/take-down              — soft-delete + availability_status='removed'; body { reason }
POST   /api/v1/admin/listings/{id}/restore                — clear deleted_at + restore availability_status='available'; body { reason }

# --- Users ---
GET    /api/v1/admin/users                                — paginated, search by email, filter by role/is_active
GET    /api/v1/admin/users/{id}                           — detail: email, role, is_active, locked_until, memberships, owned-listing count
POST   /api/v1/admin/users/{id}/lock                      — time-boxed timeout (sets User.locked_until); body { reason, hours: int }
POST   /api/v1/admin/users/{id}/unlock                    — clears User.locked_until; body { reason }
PATCH  /api/v1/admin/users/{id}                           — two distinct body shapes:
                                                            { "role": "user"|"moderator"|"admin" }      ← admin only
                                                            { "is_active": bool, "reason": str }        ← admin OR moderator

# --- Audit log (read-only) ---
GET    /api/v1/admin/audit-log                            — paginated; filter by actor_user_id, action, target_type, date range
```

**Take-down cascades (already in Phase 2 model):**
- Community take-down → `communities.deleted_at = NOW()`. The visibility helper already filters on `deleted_at IS NULL`. Listings shared *only* into the taken-down community drop out of the feed immediately. Listings shared into multiple communities stay visible via the others.
- Listing take-down → `listings.deleted_at = NOW()`, `availability_status = "removed"`. Both already supported by the Phase 2 model.

Both are reversible by re-clearing the columns.

**Lock vs. deactivate:** Lock is a time-boxed timeout (the existing `User.locked_until` column, originally for login throttling, is reused). Deactivate (`PATCH … {is_active: false}`) is the escalation — kills the session and bars login indefinitely.

**Events emitted:**
- `admin.community.taken_down` / `admin.community.restored` (one row, `household_id` = creator's household)
- `admin.listing.taken_down` / `admin.listing.restored` (one row, `household_id` = listing's owning household)
- `admin.user.locked` / `admin.user.unlocked` / `admin.user.deactivated` / `admin.user.activated` (one row, no household_id since these are platform-level)
- `admin.user.role_changed` (admin only; one row, no household_id)

All of these *also* write `core.audit_log` with `actor_user_id`, `action`, `target_type`, `target_id`, and `payload.reason`.

## 9. Admin UI (Next.js)

All under `apps/web/src/app/admin/`. Server-side gating via the backend dependencies; client-side gating to hide nav items the user can't access.

### 9.1 Sidebar

The existing sidebar (`apps/web/src/components/Sidebar.tsx`) gains a new "Admin" section, visible only when `is_at_least_moderator(user)`. Items rendered dynamically per role:

```
Admin
├── Home              [admin + moderator]
├── Users             [admin + moderator]
├── Communities       [admin + moderator]   ← new
├── Listings          [admin + moderator]   ← new
├── Audit log         [admin + moderator]
├── Settings          [admin only]
├── Flags             [admin only]
└── Banner            [admin only]
```

A small role badge (`ADMIN` amber, `MOD` stone) renders next to the user avatar in the existing top bar, so the user always knows which hat they're wearing.

### 9.2 Pages

| Route | Visible to | Description |
|---|---|---|
| `/admin` | admin + mod | Tile grid (Users, Communities, Listings, Audit; plus Settings/Flags/Banner for admin only). Status panel: admin count, signups state, maintenance banner state. 10 most-recent audit entries. |
| `/admin/users` | admin + mod | Paginated table: email · display name · role badge · is_active toggle · locked_until · created_at. Row actions per role: admin sees Role dropdown + Lock/Unlock + Activate/Deactivate; mod sees Lock/Unlock + Activate/Deactivate. Last-admin guard surfaced as disabled button + tooltip. |
| `/admin/users/[id]` | admin + mod | Detail card: email, role, is_active, locked_until, household memberships, owned-listing count, last 50 audit entries about this user. Admin also sees a "Per-user setting overrides" panel; mod does not. |
| `/admin/communities` | admin + mod | Paginated table: name · slug · member count · listing count · created_at · is_deleted. Row actions: Take down (with reason modal) · Restore. |
| `/admin/communities/[id]` | admin + mod | Detail: members, listings, creator, audit history. Take-down / restore button at top. |
| `/admin/listings` | admin + mod | Paginated table: title · owner · category · availability · communities · created_at. Row actions: Take down · Restore. |
| `/admin/listings/[id]` | admin + mod | Detail: full listing data, owner, communities, visibility, request history, audit. Take-down / restore button at top. |
| `/admin/audit-log` | admin + mod | Paginated table: when · actor email · action · target type/id · payload preview (JSON expandable). Filters: actor, action prefix, target type, date range. |
| `/admin/settings` | admin only | Registry-driven table: key · type · scopes · description · current global · override counts. Inline edit for globals (widget per `spec.type`). "View overrides" → detail page. |
| `/admin/settings/[key]` | admin only | Global value editor + two collapsible sections: household overrides (paginated, add/remove) and user overrides (same). |
| `/admin/flags` | admin only | Table: key · description · global toggle · rollout slider 0–100 · override counts. Inline editing. "+ New flag" → modal. |
| `/admin/flags/[key]` | admin only | Flag detail + household / user override editors. |
| `/admin/banner` | admin only | Single textarea bound to `maintenance_message` setting. Save publishes globally; preview shows what users will see. |

### 9.3 Reason modal

Every take-down / deactivate / lock action opens a small dialog with a required text field. Submit is disabled until the field is non-empty. Submitted text becomes `payload.reason` on both the event and audit-log entries.

### 9.4 Maintenance banner on the public site

The existing root layout calls `GET /api/v1/runtime-config` on mount (no auth). If `maintenance_message` is non-empty, render a stone-amber banner at the top across every page. Same call also gates the "Sign up" CTA against `signups_open`.

### 9.5 Page-not-found vs. forbidden

For pages a moderator should not see (`/admin/settings`, `/admin/flags`, `/admin/banner`):
- Sidebar: items hidden.
- Direct URL access: backend returns 403 from `require_admin`; the Next.js page catches it and renders a friendly "You don't have access" message with a "Back to admin home" link. We don't 404 (information hiding doesn't matter — moderators know admin features exist).

## 10. API summary

Full endpoint surface added by this spec, grouped:

```
# --- Auth-adjacent ---
GET    /api/v1/auth/me                                   — (existing) now also returns user.role
GET    /api/v1/runtime-config                            — NEW; public; whitelisted settings only

# --- Self-service settings ---
GET    /api/v1/me/settings
PUT    /api/v1/me/settings/{key}
DELETE /api/v1/me/settings/{key}
GET    /api/v1/households/{hid}/settings
PUT    /api/v1/households/{hid}/settings/{key}           — household-owner role only
DELETE /api/v1/households/{hid}/settings/{key}           — household-owner role only

# --- Admin: settings (admin only) ---
GET    /api/v1/admin/settings
GET    /api/v1/admin/settings/registry
GET    /api/v1/admin/settings/{key}
PUT    /api/v1/admin/settings/{key}
DELETE /api/v1/admin/settings/{key}
PUT    /api/v1/admin/settings/{key}/household/{hid}
DELETE /api/v1/admin/settings/{key}/household/{hid}
PUT    /api/v1/admin/settings/{key}/user/{uid}
DELETE /api/v1/admin/settings/{key}/user/{uid}

# --- Admin: feature flags (admin only) ---
GET    /api/v1/admin/flags
GET    /api/v1/admin/flags/{key}
POST   /api/v1/admin/flags
PATCH  /api/v1/admin/flags/{key}
DELETE /api/v1/admin/flags/{key}
PUT    /api/v1/admin/flags/{key}/household/{hid}
DELETE /api/v1/admin/flags/{key}/household/{hid}
PUT    /api/v1/admin/flags/{key}/user/{uid}
DELETE /api/v1/admin/flags/{key}/user/{uid}

# --- Moderation (admin + moderator) ---
GET    /api/v1/admin/users
GET    /api/v1/admin/users/{id}
PATCH  /api/v1/admin/users/{id}                          — { role } admin-only; { is_active, reason } admin+mod
POST   /api/v1/admin/users/{id}/lock                     — { reason, hours }
POST   /api/v1/admin/users/{id}/unlock                   — { reason }
GET    /api/v1/admin/communities
GET    /api/v1/admin/communities/{id}
POST   /api/v1/admin/communities/{id}/take-down          — { reason }
POST   /api/v1/admin/communities/{id}/restore            — { reason }
GET    /api/v1/admin/listings
GET    /api/v1/admin/listings/{id}
POST   /api/v1/admin/listings/{id}/take-down             — { reason }
POST   /api/v1/admin/listings/{id}/restore               — { reason }
GET    /api/v1/admin/audit-log
```

## 11. Migrations

Two new migrations, applied in order:

- **`0006_admin_role.py`** — adds `core.users.role` (default `'user'`), backfills, adds the CHECK constraint. Downgrade drops the constraint then the column.
- **`0007_app_settings.py`** — creates `core.app_settings_kv`, `core.household_settings`, `core.user_settings`, `core.feature_flag_overrides`. Adds the two partial unique indexes on `feature_flag_overrides`. Downgrade drops in reverse order.

Both round-trip cleanly (`alembic upgrade head` then `alembic downgrade -1` twice → schema matches the previous head).

## 12. Tests

Backend test files added under `apps/backend/tests/`:

- `test_admin_bootstrap.py` — bootstrap creates a user when missing; second startup is no-op; existing-user-without-admin-role is promoted; password is never overwritten.
- `test_permissions.py` — `is_admin` / `is_moderator` / `is_at_least_moderator` cover every role-state combination including `is_active=False`.
- `test_require_admin_endpoints.py` — every `/admin/*` endpoint: 401 without session, 403 for `user`, 403 for `moderator` on admin-only routes, 200 for `admin`.
- `test_require_moderator_endpoints.py` — every moderator-allowed `/admin/*` endpoint: 401 without session, 403 for `user`, 200 for `moderator` and `admin`.
- `test_settings_registry.py` — `_coerce` type-checks; bool-where-int-expected rejected; type-mismatched stored value falls back to default.
- `test_settings_resolver.py` — user override beats household beats global beats registry default; scope rejection on set; unknown key raises.
- `test_settings_endpoints.py` — full CRUD coverage across admin / household / user endpoints, including the household-owner gate.
- `test_runtime_config_endpoint.py` — public, no auth; only `public=True` keys present; non-public keys absent.
- `test_flags_resolver.py` — user override beats household beats global; `enabled_globally=true` returns True; `rollout_percent` is deterministic per user; rollout ignored when no user.
- `test_flags_endpoints.py` — CRUD coverage; overrides; deleted flag returns 404.
- `test_moderation_endpoints.py` — take-down + restore for communities and listings; `reason` required; audit log entry written; events emitted; idempotent restore.
- `test_user_management_endpoints.py` — role PATCH admin-only; is_active PATCH admin+mod; last-admin guard fires; lock / unlock round-trip; audit entries.
- `test_audit_log_endpoint.py` — list, filter by actor / action / date range; both admin and moderator can read.

Frontend tests are out-of-scope for the backend test count but the Next.js pages get the same role-gating treatment in the spec.

## 13. Security considerations

1. **All `/admin/*` endpoints gated server-side** by `require_admin` or `require_moderator`. Client-side sidebar hiding is UX, not security.
2. **Every moderator-grade write requires `reason`** (Pydantic-validated, 3–500 chars). No reason → 422.
3. **All admin / moderator writes audit-logged** to `core.audit_log`. The actor, target, action, and payload (incl. reason) are persisted. The audit log is read-only via the API (no DELETE).
4. **Last-admin guard** prevents the system from ending up with zero active admins. Triggers on any role-change-away-from-admin or `is_active=false` of the last admin.
5. **Bootstrap idempotency**: the env-var bootstrap never overwrites an existing password. Password rotation goes through the normal `POST /auth/password` flow.
6. **Bootstrap requires explicit env vars**: if `ADMIN_EMAIL` is unset, bootstrap is a no-op. No accidental admin creation in production.
7. **Public runtime-config whitelist is the registry `public` flag**, not a hardcoded list of strings. Forgetting to mark a new key as public defaults to *not* exposing it — fail-closed.
8. **Setting type-coercion is fail-closed**: a JSONB value that doesn't match the registry type returns the default and logs a WARN; it never raises into the request path.
9. **Feature-flag rollout hash uses SHA-256 over `(flag_key, user_id)`** — different flags rotate independently; same user gets a stable answer for the same flag. No global cohort lock-in.
10. **`User.role` has a DB-level CHECK constraint** so a stringly-typed bug can't insert `'superuser'` or `''`.
11. **Cascade behavior**: the API soft-deletes flags (sets `deleted_at`); the resolver then returns `False` for the key and any existing overrides become unreachable — they are *not* auto-removed. The DB-level `ON DELETE CASCADE` on `feature_flag_overrides.flag_key` is defensive for *hard* deletes (DB tools, future purge jobs). Setting tables have no cascades — orphaned rows under a deleted user/household stay (and the resolver simply doesn't find them; hard-deleting a user / household is a separate concern not addressed here).
12. **Moderator audit-log access is full read** including admin actions. Transparency is the chosen tradeoff; this is documented as a design decision rather than an oversight.
13. **No moderator can promote anyone** to any role. Role assignment is admin-only, no exceptions. This is enforced by the dependency type on the role-PATCH branch, not just by code-path inspection.

## 14. Future work (explicitly out of scope)

- **Permission system (RBAC):** if the role enum grows beyond `{user, moderator, admin}`, migrate to a permission set per user. Not needed yet; the linear hierarchy works.
- **Email notifications to admin/moderator on flagged content:** Phase 4 reporting will introduce this. The audit log is the source of truth; notifications layer on top.
- **Per-user setting bulk import / export:** out of scope.
- **Feature flag analytics (% of users seeing flag X):** would require a materialized query over overrides + rollout — defer until a real ramp is in flight.
- **Banner scheduling (publish from / until):** for now `maintenance_message` is just a string; on/off via empty/non-empty. Scheduling could live in `metadata_` later.
- **Hard delete of users / households:** today users are deactivated, not deleted. Hard delete is a GDPR-style operation deserving its own design.

## 15. Open questions

None. Every decision in the brainstorming session has a concrete answer in this spec; nothing is deferred to "decide at implementation time."

## 16. Next step

Invoke `superpowers:writing-plans` to produce a step-by-step implementation plan from this spec.
