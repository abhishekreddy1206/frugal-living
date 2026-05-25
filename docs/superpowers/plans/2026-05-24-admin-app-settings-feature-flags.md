# Admin Console, App Settings, and Feature Flags Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the three-role access model (user/moderator/admin), an env-var-seeded admin bootstrap, a 3-layer app-settings system (global / household / user) backed by a Python registry, a feature-flag service that activates the existing `core.feature_flags` table with per-household / per-user overrides, and a full Next.js admin console with moderation surface.

**Architecture:** Single cohesive `core` subsystem — no tier-specific code touched. Settings + flags are 3-layer overlays (registry default ← global ← household ← user) resolved by pure helpers in `app/services/`. Admin endpoints split by surface (`admin_users.py`, `admin_settings.py`, `admin_flags.py`, `admin_moderation.py`, `admin_audit.py`) for focus; all gated by `require_admin` or `require_moderator` dependencies. Frontend pages live under `apps/web/src/app/admin/` with sidebar + page-level role gating.

**Tech Stack:** FastAPI / SQLAlchemy 2.0 / Alembic / PostgreSQL 16 (JSONB throughout); Next.js 14 App Router / TypeScript / Tailwind. Bcrypt via existing passlib pin.

**Spec:** `docs/superpowers/specs/2026-05-24-admin-app-settings-feature-flags-design.md`

---

## File Structure

### Backend — new

```
apps/backend/alembic/versions/
  0006_admin_role.py                            # User.role + CHECK constraint
  0007_app_settings.py                          # 4 tables: app_settings_kv, household_settings, user_settings, feature_flag_overrides

apps/backend/app/services/auth/
  permissions.py                                # is_admin, is_moderator, is_at_least_moderator, assert_not_last_admin

apps/backend/app/services/admin/
  bootstrap.py                                  # idempotent admin bootstrap from env vars
  users.py                                      # role/active/lock service helpers (audit + events)
  moderation.py                                 # community/listing take-down/restore service helpers

apps/backend/app/services/settings/
  registry.py                                   # SettingSpec dataclass + SETTING_REGISTRY dict
  resolver.py                                   # get_setting, set_setting, _coerce

apps/backend/app/services/flags/
  resolver.py                                   # is_enabled with override resolution + rollout-percent hashing
  admin.py                                      # create/update/delete flag, set/clear overrides

apps/backend/app/routers/
  admin_users.py                                # /admin/users/*
  admin_settings.py                             # /admin/settings/*
  admin_flags.py                                # /admin/flags/*
  admin_moderation.py                           # /admin/{communities,listings}/*
  admin_audit.py                                # /admin/audit-log
  me_settings.py                                # /me/settings/*, /households/{id}/settings/*
  runtime_config.py                             # public /runtime-config

apps/backend/app/schemas/
  admin.py                                      # all request/response shapes for admin endpoints
  settings.py                                   # SettingRead, SettingWrite, RegistryEntry
  flags.py                                      # FeatureFlagRead, FeatureFlagWrite, OverrideRead, OverrideWrite
```

### Backend — modified

```
apps/backend/app/models/core.py                 # + User.role; + AppSettingKv, HouseholdSetting, UserSetting, FeatureFlagOverride
apps/backend/app/auth.py                        # + require_admin, require_moderator, CurrentAdmin, CurrentModerator; call bootstrap_admin
apps/backend/app/config.py                      # + admin_email, admin_password, admin_display_name
apps/backend/app/main.py                        # mount 7 new routers
apps/backend/app/routers/auth.py                # MeResponse now includes role
apps/backend/tests/conftest.py                  # + admin_user, moderator_user fixtures; wipe new tables in _clean_household_data
```

### Backend — tests (new)

```
apps/backend/tests/test_permissions.py
apps/backend/tests/test_admin_bootstrap.py
apps/backend/tests/test_require_admin_endpoints.py
apps/backend/tests/test_require_moderator_endpoints.py
apps/backend/tests/test_settings_registry.py
apps/backend/tests/test_settings_resolver.py
apps/backend/tests/test_settings_admin_endpoints.py
apps/backend/tests/test_settings_self_service_endpoints.py
apps/backend/tests/test_runtime_config_endpoint.py
apps/backend/tests/test_flags_resolver.py
apps/backend/tests/test_flags_admin_endpoints.py
apps/backend/tests/test_user_management_endpoints.py
apps/backend/tests/test_moderation_endpoints.py
apps/backend/tests/test_audit_log_endpoint.py
```

### Frontend — new

```
apps/web/src/components/
  RoleBadge.tsx                                 # ADMIN/MOD pill
  ReasonModal.tsx                               # shared modal for moderator writes
  MaintenanceBanner.tsx                         # public banner driven by runtime-config

apps/web/src/app/admin/
  layout.tsx                                    # client-side role gate + admin sidebar
  page.tsx                                      # admin home
  users/page.tsx
  users/[id]/page.tsx
  communities/page.tsx
  communities/[id]/page.tsx
  listings/page.tsx
  listings/[id]/page.tsx
  audit-log/page.tsx
  settings/page.tsx
  settings/[key]/page.tsx
  flags/page.tsx
  flags/[key]/page.tsx
  banner/page.tsx
```

### Frontend — modified

```
apps/web/src/lib/types.ts                       # + Role, Setting, SettingSpec, FeatureFlag, AuditLogEntry, etc.
apps/web/src/lib/api.ts                         # + 25+ admin API functions
apps/web/src/components/Sidebar.tsx             # + Admin section conditional on role
apps/web/src/app/layout.tsx                     # mount MaintenanceBanner globally
```

---

## Phase 1 — Foundation (role, permissions, bootstrap)

### Task 1: Migration 0006 — `users.role` column

**Files:**
- Create: `apps/backend/alembic/versions/0006_admin_role.py`
- Modify: `apps/backend/app/models/core.py:27-41` (add `role` column to User)

- [ ] **Step 1: Write the migration**

```python
"""admin role on users

Revision ID: 0006_admin_role
Revises: 0005_community_listings
Create Date: 2026-05-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_admin_role"
down_revision = "0005_community_listings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=16), nullable=False, server_default="user"),
        schema="core",
    )
    op.create_check_constraint(
        "users_role_valid",
        "users",
        "role IN ('user', 'moderator', 'admin')",
        schema="core",
    )


def downgrade() -> None:
    op.drop_constraint("users_role_valid", "users", schema="core", type_="check")
    op.drop_column("users", "role", schema="core")
```

- [ ] **Step 2: Run the migration**

```bash
cd apps/backend
uv run alembic upgrade head
```

Expected: `INFO  [alembic.runtime.migration] Running upgrade 0005_community_listings -> 0006_admin_role, admin role on users`

- [ ] **Step 3: Verify downgrade round-trips**

```bash
uv run alembic downgrade -1 && uv run alembic upgrade head
```

Expected: both commands succeed without errors.

- [ ] **Step 4: Add `role` to the `User` model**

Edit `apps/backend/app/models/core.py`, locate the `User` class (line 27), and insert after `is_active` (line 35):

```python
    role: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
    # "user" | "moderator" | "admin" — enforced by DB CHECK constraint users_role_valid
```

- [ ] **Step 5: Run a smoke check that existing tests still pass**

```bash
cd apps/backend
uv run pytest tests/test_auth.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/alembic/versions/0006_admin_role.py apps/backend/app/models/core.py
git commit -m "feat(admin): migration 0006 + User.role column"
```

---

### Task 2: Permissions helpers

**Files:**
- Create: `apps/backend/app/services/auth/permissions.py`
- Create: `apps/backend/tests/test_permissions.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/test_permissions.py
"""Pure-function tests for permission helpers — no DB required."""
from datetime import datetime, timezone

from app.models.core import User
from app.services.auth.permissions import (
    is_admin,
    is_at_least_moderator,
    is_moderator,
)


def _user(role: str, active: bool = True) -> User:
    return User(
        email=f"{role}@test.local",
        role=role,
        is_active=active,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def test_is_admin_true_for_active_admin():
    assert is_admin(_user("admin")) is True


def test_is_admin_false_for_inactive_admin():
    assert is_admin(_user("admin", active=False)) is False


def test_is_admin_false_for_moderator():
    assert is_admin(_user("moderator")) is False


def test_is_admin_false_for_user():
    assert is_admin(_user("user")) is False


def test_is_moderator_true_only_for_active_moderator():
    assert is_moderator(_user("moderator")) is True
    assert is_moderator(_user("moderator", active=False)) is False
    assert is_moderator(_user("admin")) is False
    assert is_moderator(_user("user")) is False


def test_is_at_least_moderator_includes_admin():
    assert is_at_least_moderator(_user("admin")) is True
    assert is_at_least_moderator(_user("moderator")) is True
    assert is_at_least_moderator(_user("user")) is False
    assert is_at_least_moderator(_user("admin", active=False)) is False
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
cd apps/backend
uv run pytest tests/test_permissions.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.services.auth.permissions'`

- [ ] **Step 3: Create the permissions module**

```python
# apps/backend/app/services/auth/permissions.py
"""Pure-function role checks. No I/O, no DB. Reused by auth dependencies and routes."""
from __future__ import annotations

from app.models.core import User


def is_admin(u: User) -> bool:
    return u.role == "admin" and u.is_active


def is_moderator(u: User) -> bool:
    return u.role == "moderator" and u.is_active


def is_at_least_moderator(u: User) -> bool:
    return u.role in ("admin", "moderator") and u.is_active
```

If the `app/services/auth/` directory doesn't already exist (it does — `sessions.py` lives there), no `__init__.py` work is needed; if it does not, add an empty `__init__.py` first.

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
uv run pytest tests/test_permissions.py -q
```

Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/services/auth/permissions.py apps/backend/tests/test_permissions.py
git commit -m "feat(admin): permissions helpers (is_admin, is_moderator, is_at_least_moderator)"
```

---

### Task 3: Auth dependencies + last-admin guard

**Files:**
- Modify: `apps/backend/app/auth.py` (append at end)
- Add helper in: `apps/backend/app/services/auth/permissions.py`

- [ ] **Step 1: Add `assert_not_last_admin` to permissions.py**

Append to `apps/backend/app/services/auth/permissions.py`:

```python
from fastapi import HTTPException
from sqlalchemy.orm import Session as DbSession


def assert_not_last_admin(db: DbSession, target_user: User) -> None:
    """Block role-change-away-from-admin or deactivation of the last active admin."""
    if target_user.role != "admin":
        return
    other_admins = (
        db.query(User)
        .filter(
            User.id != target_user.id,
            User.role == "admin",
            User.is_active.is_(True),
        )
        .count()
    )
    if other_admins == 0:
        raise HTTPException(status_code=400, detail="cannot remove the last active admin")
```

- [ ] **Step 2: Add the dependencies to `app/auth.py`**

Append to `apps/backend/app/auth.py`:

```python
from app.services.auth.permissions import is_admin, is_at_least_moderator


def require_admin(user: CurrentUser) -> User:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="admin required")
    return user


def require_moderator(user: CurrentUser) -> User:
    """Pass if user is admin OR moderator. Used for moderation endpoints."""
    if not is_at_least_moderator(user):
        raise HTTPException(status_code=403, detail="moderator required")
    return user


CurrentAdmin = Annotated[User, Depends(require_admin)]
CurrentModerator = Annotated[User, Depends(require_moderator)]
```

- [ ] **Step 3: Run existing tests for regression**

```bash
cd apps/backend
uv run pytest -q --no-header 2>&1 | tail -5
```

Expected: same pass count as before the task (the new dependencies aren't used yet — no breakage).

- [ ] **Step 4: Commit**

```bash
git add apps/backend/app/auth.py apps/backend/app/services/auth/permissions.py
git commit -m "feat(admin): require_admin / require_moderator deps + last-admin guard"
```

---

### Task 4: Admin bootstrap (config + service + wire-in)

**Files:**
- Modify: `apps/backend/app/config.py` (add 3 fields)
- Modify: `apps/backend/.env.example` (document the new vars)
- Create: `apps/backend/app/services/admin/__init__.py` (empty)
- Create: `apps/backend/app/services/admin/bootstrap.py`
- Create: `apps/backend/tests/test_admin_bootstrap.py`
- Modify: `apps/backend/app/auth.py` (call bootstrap_admin from seed_reference_data)

- [ ] **Step 1: Add env-var fields to config**

Edit `apps/backend/app/config.py` and append before `model_config`:

```python
    # Admin bootstrap — leave empty in production unless you want a default admin seeded.
    admin_email: str | None = None
    admin_password: str | None = None
    admin_display_name: str | None = None
```

Update `.env.example`:

```bash
# Optional: bootstrap a default admin on app startup.
# If set, the user is created (if missing) or promoted to admin (if present).
# The password is only used at first creation; rotate via POST /auth/password.
ADMIN_EMAIL=
ADMIN_PASSWORD=
ADMIN_DISPLAY_NAME=
```

- [ ] **Step 2: Write failing tests**

```python
# apps/backend/tests/test_admin_bootstrap.py
"""Bootstrap is idempotent, never overwrites passwords, promotes existing users."""
from __future__ import annotations

import uuid

import pytest

from app.auth import DEV_USER_ID
from app.db import SessionLocal
from app.models.core import AuditLog, Household, HouseholdMember, User
from app.services.admin.bootstrap import bootstrap_admin


@pytest.fixture
def fresh_email() -> str:
    return f"admin-{uuid.uuid4().hex[:8]}@test.local"


def test_bootstrap_noop_when_email_unset(db, fresh_email):
    before = db.query(User).count()
    bootstrap_admin(db, email=None, password="x", display_name=None)
    assert db.query(User).count() == before


def test_bootstrap_creates_user_when_missing(fresh_email):
    with SessionLocal() as db_:
        bootstrap_admin(db_, email=fresh_email, password="bootstrap-pw", display_name="Boss")
        db_.commit()
    with SessionLocal() as db_:
        u = db_.query(User).filter_by(email=fresh_email).one()
        assert u.role == "admin"
        assert u.is_active is True
        assert u.email_verified is True
        assert u.hashed_password is not None
        # Has a personal household with owner membership
        membership = db_.query(HouseholdMember).filter_by(user_id=u.id).one()
        assert membership.role == "owner"
        hh = db_.get(Household, membership.household_id)
        assert hh.name == "Boss's Household"
        # Audit row written
        audit = db_.query(AuditLog).filter_by(action="admin.bootstrap.created").all()
        assert any(a.payload.get("email") == fresh_email for a in audit)


def test_bootstrap_promotes_existing_non_admin(fresh_email):
    # Pre-create a regular user
    with SessionLocal() as db_:
        u = User(email=fresh_email, hashed_password="$2b$12$abcdefg", role="user")
        db_.add(u)
        db_.commit()

    with SessionLocal() as db_:
        bootstrap_admin(db_, email=fresh_email, password="ignored", display_name="X")
        db_.commit()

    with SessionLocal() as db_:
        u = db_.query(User).filter_by(email=fresh_email).one()
        assert u.role == "admin"
        # Password untouched
        assert u.hashed_password == "$2b$12$abcdefg"
        audit = db_.query(AuditLog).filter_by(action="admin.bootstrap.promoted").all()
        assert any(a.payload.get("email") == fresh_email for a in audit)


def test_bootstrap_idempotent_on_existing_admin(fresh_email):
    with SessionLocal() as db_:
        bootstrap_admin(db_, email=fresh_email, password="pw", display_name="Z")
        db_.commit()
    # Second run should not duplicate audit rows
    with SessionLocal() as db_:
        before = db_.query(AuditLog).filter_by(action="admin.bootstrap.created").count()
        bootstrap_admin(db_, email=fresh_email, password="pw", display_name="Z")
        db_.commit()
        after = db_.query(AuditLog).filter_by(action="admin.bootstrap.created").count()
        assert after == before
```

- [ ] **Step 3: Run tests to confirm failure**

```bash
cd apps/backend
uv run pytest tests/test_admin_bootstrap.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.services.admin'`

- [ ] **Step 4: Create the bootstrap service**

`apps/backend/app/services/admin/__init__.py`: empty file.

`apps/backend/app/services/admin/bootstrap.py`:

```python
"""Idempotent admin bootstrap from env vars. Runs at app startup."""
from __future__ import annotations

import logging

from passlib.context import CryptContext
from sqlalchemy.orm import Session as DbSession

from app.models.core import AuditLog, Household, HouseholdMember, User

logger = logging.getLogger(__name__)

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def bootstrap_admin(
    db: DbSession,
    *,
    email: str | None,
    password: str | None,
    display_name: str | None,
) -> None:
    """Idempotent: create the bootstrap admin if missing; ensure role=admin if present.

    NEVER overwrites an existing password. Rotate via POST /auth/password.
    No-op when email is falsy (production hardening: explicit opt-in only).
    """
    if not email:
        return
    if not password:
        logger.warning("ADMIN_EMAIL set without ADMIN_PASSWORD; bootstrap skipped")
        return

    existing = db.query(User).filter_by(email=email).one_or_none()
    if existing is None:
        name = display_name or email.split("@")[0]
        user = User(
            email=email,
            hashed_password=_pwd.hash(password),
            display_name=name,
            role="admin",
            is_active=True,
            email_verified=True,
        )
        db.add(user)
        db.flush()
        household = Household(name=f"{name}'s Household", size=1)
        db.add(household)
        db.flush()
        db.add(HouseholdMember(user_id=user.id, household_id=household.id, role="owner"))
        db.add(AuditLog(
            actor_user_id=user.id,
            action="admin.bootstrap.created",
            target_type="user",
            target_id=user.id,
            payload={"email": email},
        ))
        logger.info("bootstrap admin created: %s", email)
        return

    # User exists; ensure admin role + active. Never touch the password.
    if existing.role != "admin" or not existing.is_active:
        existing.role = "admin"
        existing.is_active = True
        db.add(AuditLog(
            actor_user_id=existing.id,
            action="admin.bootstrap.promoted",
            target_type="user",
            target_id=existing.id,
            payload={"email": email},
        ))
        logger.info("bootstrap admin promoted: %s", email)
```

- [ ] **Step 5: Wire into `seed_reference_data`**

Edit `apps/backend/app/auth.py`, replace the body of `seed_reference_data`:

```python
def seed_reference_data(db: DbSession) -> None:
    """Seed global, not-user-specific reference data on app startup.

    Replaces the old `seed_dev_fixtures` — the dev user/household auto-seed is
    gone; new users sign up through the UI. Also bootstraps the optional admin
    account from ADMIN_EMAIL/ADMIN_PASSWORD env vars (no-op when unset).
    """
    seed_starter_ingredients(db)
    seed_badge_definitions(db)
    bootstrap_admin(
        db,
        email=settings.admin_email,
        password=settings.admin_password,
        display_name=settings.admin_display_name,
    )
```

And add the import at the top:

```python
from app.services.admin.bootstrap import bootstrap_admin
```

- [ ] **Step 6: Run tests to confirm they pass**

```bash
uv run pytest tests/test_admin_bootstrap.py -q
```

Expected: `4 passed`.

- [ ] **Step 7: Confirm whole suite still green**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: existing tests pass; total bumps by 4 (+ 7 from Task 2 = 11 new tests).

- [ ] **Step 8: Commit**

```bash
git add apps/backend/app/config.py apps/backend/.env.example \
        apps/backend/app/services/admin/__init__.py \
        apps/backend/app/services/admin/bootstrap.py \
        apps/backend/app/auth.py \
        apps/backend/tests/test_admin_bootstrap.py
git commit -m "feat(admin): env-var-seeded idempotent admin bootstrap"
```

---

### Task 5: Conftest fixtures for admin / moderator users

**Files:**
- Modify: `apps/backend/tests/conftest.py`

- [ ] **Step 1: Add stable IDs and helpers**

Edit `apps/backend/tests/conftest.py`. After `SECOND_USER_EMAIL = "second@frugal-living.local"` (line 63), insert:

```python
ADMIN_USER_ID = _uuid_for_fixture.UUID("00000000-0000-0000-0000-000000000021")
ADMIN_USER_EMAIL = "admin@frugal-living.local"

MODERATOR_USER_ID = _uuid_for_fixture.UUID("00000000-0000-0000-0000-000000000031")
MODERATOR_USER_EMAIL = "moderator@frugal-living.local"
```

- [ ] **Step 2: Extend `_seed_test_user_and_household` to seed admin + moderator**

In the same function, before `db_.commit()`, add:

```python
        admin_u = db_.get(User, ADMIN_USER_ID)
        if admin_u is None:
            db_.add(User(
                id=ADMIN_USER_ID, email=ADMIN_USER_EMAIL,
                display_name="Admin User", role="admin", is_active=True,
            ))
            db_.flush()
        else:
            admin_u.role = "admin"
            admin_u.is_active = True

        mod_u = db_.get(User, MODERATOR_USER_ID)
        if mod_u is None:
            db_.add(User(
                id=MODERATOR_USER_ID, email=MODERATOR_USER_EMAIL,
                display_name="Moderator User", role="moderator", is_active=True,
            ))
            db_.flush()
        else:
            mod_u.role = "moderator"
            mod_u.is_active = True
```

- [ ] **Step 3: Add a helper to override dependencies as a specific user**

After `_override_get_current_household` (line 148), add:

```python
def _override_as(user_id):
    def _inner():
        with SessionLocal() as db_:
            return db_.get(User, user_id)
    return _inner


def use_admin_for(test_app):
    """Test helper: override get_current_user to return the admin fixture user."""
    from app.auth import get_current_user
    test_app.dependency_overrides[get_current_user] = _override_as(ADMIN_USER_ID)


def use_moderator_for(test_app):
    from app.auth import get_current_user
    test_app.dependency_overrides[get_current_user] = _override_as(MODERATOR_USER_ID)
```

- [ ] **Step 4: Add admin / moderator fixtures**

After `second_user` fixture (line 246), add:

```python
@pytest.fixture
def admin_user(db) -> User:
    u = db.get(User, ADMIN_USER_ID)
    assert u is not None and u.role == "admin"
    return u


@pytest.fixture
def moderator_user(db) -> User:
    u = db.get(User, MODERATOR_USER_ID)
    assert u is not None and u.role == "moderator"
    return u


@pytest.fixture
def as_admin():
    """Context-manager fixture: makes get_current_user resolve to the admin user
    for the duration of the test. Restores the previous override on teardown."""
    from app.auth import get_current_user
    prev = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = _override_as(ADMIN_USER_ID)
    yield
    if prev is None:
        app.dependency_overrides.pop(get_current_user, None)
    else:
        app.dependency_overrides[get_current_user] = prev


@pytest.fixture
def as_moderator():
    from app.auth import get_current_user
    prev = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = _override_as(MODERATOR_USER_ID)
    yield
    if prev is None:
        app.dependency_overrides.pop(get_current_user, None)
    else:
        app.dependency_overrides[get_current_user] = prev
```

- [ ] **Step 5: Run the full suite to confirm no regressions**

```bash
cd apps/backend
uv run pytest -q 2>&1 | tail -3
```

Expected: same pass count as before (fixtures are passive until tests use them).

- [ ] **Step 6: Commit**

```bash
git add apps/backend/tests/conftest.py
git commit -m "test(admin): conftest fixtures for admin and moderator users"
```

---

## Phase 2 — App settings backend

### Task 6: Migration 0007 + settings models

**Files:**
- Create: `apps/backend/alembic/versions/0007_app_settings.py`
- Modify: `apps/backend/app/models/core.py` (append 4 model classes)
- Modify: `apps/backend/tests/conftest.py` (wipe new tables in `_clean_household_data`)

- [ ] **Step 1: Write the migration**

```python
"""app settings + feature flag overrides

Revision ID: 0007_app_settings
Revises: 0006_admin_role
Create Date: 2026-05-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0007_app_settings"
down_revision = "0006_admin_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings_kv",
        sa.Column("key", sa.String(length=120), primary_key=True),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by_user_id", UUID(as_uuid=True),
                  sa.ForeignKey("core.users.id"), nullable=True),
        schema="core",
    )

    op.create_table(
        "household_settings",
        sa.Column("household_id", UUID(as_uuid=True),
                  sa.ForeignKey("core.households.id"), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by_user_id", UUID(as_uuid=True),
                  sa.ForeignKey("core.users.id"), nullable=True),
        sa.PrimaryKeyConstraint("household_id", "key"),
        schema="core",
    )

    op.create_table(
        "user_settings",
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "key"),
        schema="core",
    )

    op.create_table(
        "feature_flag_overrides",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("flag_key", sa.String(length=120),
                  sa.ForeignKey("core.feature_flags.key", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("household_id", UUID(as_uuid=True),
                  sa.ForeignKey("core.households.id"), nullable=True),
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("core.users.id"), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("created_by_user_id", UUID(as_uuid=True),
                  sa.ForeignKey("core.users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "(household_id IS NULL) <> (user_id IS NULL)",
            name="ff_override_xor",
        ),
        schema="core",
    )

    # Partial unique indexes (a flag can have at most one row per scope target)
    op.create_index(
        "ux_flag_override_household",
        "feature_flag_overrides",
        ["flag_key", "household_id"],
        unique=True,
        schema="core",
        postgresql_where=sa.text("user_id IS NULL"),
    )
    op.create_index(
        "ux_flag_override_user",
        "feature_flag_overrides",
        ["flag_key", "user_id"],
        unique=True,
        schema="core",
        postgresql_where=sa.text("household_id IS NULL"),
    )

    # feature_flags.key must be UNIQUE (already is per 0002) for the FK to work.
    # Defensive assert: no-op if already there.


def downgrade() -> None:
    op.drop_index("ux_flag_override_user", table_name="feature_flag_overrides", schema="core")
    op.drop_index("ux_flag_override_household", table_name="feature_flag_overrides", schema="core")
    op.drop_table("feature_flag_overrides", schema="core")
    op.drop_table("user_settings", schema="core")
    op.drop_table("household_settings", schema="core")
    op.drop_table("app_settings_kv", schema="core")
```

- [ ] **Step 2: Run + downgrade round-trip**

```bash
cd apps/backend
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
```

Expected: all three commands succeed.

- [ ] **Step 3: Add model classes to `core.py`**

Append to `apps/backend/app/models/core.py`:

```python
class AppSettingKv(Base):
    """Global app settings key/value store. Configuration, not domain data —
    deliberate Rule-3/Rule-4 deviation: no metadata_, no deleted_at. Lifecycle
    is via DELETE; history lives in core.audit_log."""
    __tablename__ = "app_settings_kv"
    __table_args__ = {"schema": "core"}

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=True
    )


class HouseholdSetting(Base):
    """Per-household setting override. Same Rule-3/4 deviation as AppSettingKv."""
    __tablename__ = "household_settings"
    __table_args__ = {"schema": "core"}

    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=True
    )


class UserSetting(Base):
    """Per-user setting override. Same Rule-3/4 deviation as AppSettingKv."""
    __tablename__ = "user_settings"
    __table_args__ = {"schema": "core"}

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FeatureFlagOverride(Base):
    """Per-household or per-user override for a FeatureFlag. XOR on scope columns."""
    __tablename__ = "feature_flag_overrides"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    flag_key: Mapped[str] = mapped_column(
        String(120), ForeignKey("core.feature_flags.key", ondelete="CASCADE"), nullable=False
    )
    household_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

- [ ] **Step 4: Wipe new tables in conftest `_clean_household_data`**

In `apps/backend/tests/conftest.py`, add imports for the new models:

```python
from app.models.core import (
    AppSettingKv, AuditLog, Event, FeatureFlagOverride,
    Household, HouseholdMember, HouseholdSetting,
    Subscription, User, UserSetting,
)
```

And inside `_clean_household_data`, before `db_.commit()`, add:

```python
        db_.query(FeatureFlagOverride).delete()
        db_.query(UserSetting).delete()
        db_.query(HouseholdSetting).delete()
        db_.query(AppSettingKv).delete()
```

- [ ] **Step 5: Smoke-check existing tests still pass**

```bash
uv run pytest -q 2>&1 | tail -3
```

Expected: same pass count as before.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/alembic/versions/0007_app_settings.py \
        apps/backend/app/models/core.py \
        apps/backend/tests/conftest.py
git commit -m "feat(admin): migration 0007 + settings/flag-override models"
```

---

### Task 7: Settings registry

**Files:**
- Create: `apps/backend/app/services/settings/__init__.py` (empty)
- Create: `apps/backend/app/services/settings/registry.py`
- Create: `apps/backend/tests/test_settings_registry.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/test_settings_registry.py
"""Registry shape is correct and complete."""
import pytest

from app.services.settings.registry import SETTING_REGISTRY, SettingSpec


def test_every_setting_has_a_default_of_the_declared_type():
    for key, spec in SETTING_REGISTRY.items():
        # bool must not pass through as int (Python's bool is int subclass)
        if spec.type is int:
            assert isinstance(spec.default, int) and not isinstance(spec.default, bool), key
        else:
            assert isinstance(spec.default, spec.type), key


def test_every_setting_scope_subset_is_legal():
    legal = {"global", "household", "user"}
    for key, spec in SETTING_REGISTRY.items():
        assert set(spec.scopes).issubset(legal), key
        assert len(spec.scopes) >= 1, key


def test_public_settings_are_global_only():
    """Anything exposed via /runtime-config must be a global value (no scope-resolved leak)."""
    for key, spec in SETTING_REGISTRY.items():
        if spec.public:
            assert "global" in spec.scopes, key


def test_known_seeded_keys_present():
    for k in ("signups_open", "maintenance_message", "default_ai_model",
              "briefing_hour_local", "theme", "email_notifications"):
        assert k in SETTING_REGISTRY


def test_setting_spec_is_frozen():
    spec = next(iter(SETTING_REGISTRY.values()))
    with pytest.raises(Exception):
        spec.type = str  # type: ignore[misc]
```

- [ ] **Step 2: Run test to confirm failure**

```bash
uv run pytest tests/test_settings_registry.py -q
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create the registry**

`apps/backend/app/services/settings/__init__.py`: empty file.

`apps/backend/app/services/settings/registry.py`:

```python
"""Setting registry — source of truth for what settings exist, their types,
their defaults, and which scopes may override them."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

Scope = str  # "global" | "household" | "user"


@dataclass(frozen=True)
class SettingSpec:
    type: type
    default: Any
    scopes: tuple[Scope, ...]
    description: str
    public: bool = False  # exposed via /api/v1/runtime-config when True


SETTING_REGISTRY: dict[str, SettingSpec] = {
    # --- Operator-only globals ---
    "signups_open": SettingSpec(
        type=bool, default=True, scopes=("global",),
        description="Allow new account signups", public=True,
    ),
    "maintenance_message": SettingSpec(
        type=str, default="", scopes=("global",),
        description="Public banner shown across all pages; empty = no banner",
        public=True,
    ),
    "llm_cli_concurrency": SettingSpec(
        type=int, default=4, scopes=("global",),
        description="Max in-flight Claude CLI subprocess calls",
    ),

    # --- Cascadable defaults ---
    "default_ai_model": SettingSpec(
        type=str, default="sonnet", scopes=("global", "household"),
        description="Default Claude model for new AI calls",
    ),
    "briefing_hour_local": SettingSpec(
        type=int, default=7, scopes=("global", "household", "user"),
        description="Local hour (0-23) when daily briefings are generated",
    ),
    "pantry_expiry_warn_days": SettingSpec(
        type=int, default=3, scopes=("global", "household"),
        description="Warn N days before pantry items expire",
    ),

    # --- User-only preferences ---
    "theme": SettingSpec(
        type=str, default="warm", scopes=("user",),
        description="UI theme: 'warm' | 'muted'",
    ),
    "email_notifications": SettingSpec(
        type=bool, default=True, scopes=("user",),
        description="Receive email notifications",
    ),
}
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_settings_registry.py -q
```

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/services/settings/__init__.py \
        apps/backend/app/services/settings/registry.py \
        apps/backend/tests/test_settings_registry.py
git commit -m "feat(admin): settings registry"
```

---

### Task 8: Settings resolver (get / set / _coerce)

**Files:**
- Create: `apps/backend/app/services/settings/resolver.py`
- Create: `apps/backend/tests/test_settings_resolver.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/test_settings_resolver.py
"""Resolver picks user > household > global > registry default, and validates types."""
import pytest

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.core import (
    AppSettingKv, HouseholdSetting, User, UserSetting,
)
from app.services.settings.resolver import get_setting, set_setting


def test_default_when_no_override(db):
    # `theme` has scopes=("user",) only; with no row, returns registry default
    user = db.get(User, DEV_USER_ID)
    assert get_setting(db, "theme", user=user) == "warm"


def test_user_override_takes_precedence(db):
    user = db.get(User, DEV_USER_ID)
    db.add(UserSetting(user_id=user.id, key="theme", value="muted"))
    db.flush()
    assert get_setting(db, "theme", user=user) == "muted"


def test_household_override_when_scope_includes_household(db):
    # `briefing_hour_local` is global+household+user; place a household value
    db.add(HouseholdSetting(household_id=DEV_HOUSEHOLD_ID, key="briefing_hour_local", value=9))
    db.flush()
    from app.models.core import Household
    hh = db.get(Household, DEV_HOUSEHOLD_ID)
    assert get_setting(db, "briefing_hour_local", household=hh) == 9


def test_user_beats_household_beats_global(db):
    user = db.get(User, DEV_USER_ID)
    from app.models.core import Household
    hh = db.get(Household, DEV_HOUSEHOLD_ID)
    db.add(AppSettingKv(key="briefing_hour_local", value=6))
    db.add(HouseholdSetting(household_id=hh.id, key="briefing_hour_local", value=9))
    db.add(UserSetting(user_id=user.id, key="briefing_hour_local", value=11))
    db.flush()
    assert get_setting(db, "briefing_hour_local", user=user, household=hh) == 11


def test_set_setting_rejects_wrong_type(db):
    user = db.get(User, DEV_USER_ID)
    with pytest.raises(ValueError, match="expects bool"):
        set_setting(db, "signups_open", "yes", scope="global", scope_id=None, actor=user)


def test_set_setting_rejects_bool_where_int_expected(db):
    user = db.get(User, DEV_USER_ID)
    with pytest.raises(ValueError, match="expects int"):
        set_setting(db, "llm_cli_concurrency", True, scope="global", scope_id=None, actor=user)


def test_set_setting_rejects_scope_not_in_registry(db):
    user = db.get(User, DEV_USER_ID)
    with pytest.raises(ValueError, match="not overridable at user scope"):
        set_setting(db, "signups_open", False, scope="user", scope_id=user.id, actor=user)


def test_coerce_falls_back_on_type_drift(db, caplog):
    user = db.get(User, DEV_USER_ID)
    # Write an int into a str-typed field directly (bypassing set_setting)
    db.add(UserSetting(user_id=user.id, key="theme", value=42))
    db.flush()
    import logging
    with caplog.at_level(logging.WARNING):
        val = get_setting(db, "theme", user=user)
    assert val == "warm"  # registry default
    assert any("theme" in r.message for r in caplog.records)


def test_set_setting_writes_audit_log(db):
    from app.models.core import AuditLog
    user = db.get(User, DEV_USER_ID)
    set_setting(db, "signups_open", False, scope="global", scope_id=None, actor=user)
    db.flush()
    rows = db.query(AuditLog).filter_by(action="admin.setting.set").all()
    assert any(r.payload.get("key") == "signups_open" for r in rows)


def test_unknown_key_raises(db):
    user = db.get(User, DEV_USER_ID)
    with pytest.raises(KeyError):
        get_setting(db, "nonexistent_key", user=user)
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/test_settings_resolver.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.services.settings.resolver'`.

- [ ] **Step 3: Create the resolver**

`apps/backend/app/services/settings/resolver.py`:

```python
"""Resolver: get_setting(user/hh/global/default), set_setting(scope), with type checks."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session as DbSession

from app.models.core import (
    AppSettingKv, AuditLog, Household, HouseholdSetting, User, UserSetting,
)
from app.services.settings.registry import SETTING_REGISTRY, Scope, SettingSpec

logger = logging.getLogger(__name__)


def _coerce(value: Any, spec: SettingSpec, *, key: str) -> Any:
    """Type-check JSONB-decoded value. Return default + log on mismatch (fail-closed)."""
    if isinstance(value, spec.type) and not (spec.type is int and isinstance(value, bool)):
        return value
    logger.warning(
        "setting %s has type %s, expected %s; falling back to default",
        key, type(value).__name__, spec.type.__name__,
    )
    return spec.default


def get_setting(
    db: DbSession,
    key: str,
    *,
    user: User | None = None,
    household: Household | None = None,
) -> Any:
    """Resolve a setting value: user → household → global → registry default."""
    spec = SETTING_REGISTRY[key]  # KeyError on unknown key (programmer bug)

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


def set_setting(
    db: DbSession,
    key: str,
    value: Any,
    *,
    scope: Scope,
    scope_id: uuid.UUID | None,
    actor: User,
) -> None:
    """Upsert a setting at the given scope. Writes audit log. Caller commits."""
    spec = SETTING_REGISTRY[key]
    if scope not in spec.scopes:
        raise ValueError(f"{key} is not overridable at {scope} scope")
    if spec.type is int and isinstance(value, bool):
        raise ValueError(f"{key} expects {spec.type.__name__}, got bool")
    if not isinstance(value, spec.type):
        raise ValueError(f"{key} expects {spec.type.__name__}, got {type(value).__name__}")

    if scope == "global":
        row = db.get(AppSettingKv, key)
        if row is None:
            db.add(AppSettingKv(key=key, value=value, updated_by_user_id=actor.id))
        else:
            row.value = value
            row.updated_by_user_id = actor.id
    elif scope == "household":
        assert scope_id is not None
        row = db.get(HouseholdSetting, (scope_id, key))
        if row is None:
            db.add(HouseholdSetting(
                household_id=scope_id, key=key, value=value,
                updated_by_user_id=actor.id,
            ))
        else:
            row.value = value
            row.updated_by_user_id = actor.id
    elif scope == "user":
        assert scope_id is not None
        row = db.get(UserSetting, (scope_id, key))
        if row is None:
            db.add(UserSetting(user_id=scope_id, key=key, value=value))
        else:
            row.value = value

    db.add(AuditLog(
        actor_user_id=actor.id,
        action="admin.setting.set",
        target_type="setting",
        target_id=None,
        payload={"key": key, "scope": scope, "scope_id": str(scope_id) if scope_id else None, "value": value},
    ))


def clear_setting(
    db: DbSession,
    key: str,
    *,
    scope: Scope,
    scope_id: uuid.UUID | None,
    actor: User,
) -> None:
    """Delete a setting at the given scope (returns to next-layer-down resolution)."""
    if scope == "global":
        row = db.get(AppSettingKv, key)
    elif scope == "household":
        assert scope_id is not None
        row = db.get(HouseholdSetting, (scope_id, key))
    elif scope == "user":
        assert scope_id is not None
        row = db.get(UserSetting, (scope_id, key))
    else:
        raise ValueError(f"unknown scope: {scope}")

    if row is not None:
        db.delete(row)
        db.add(AuditLog(
            actor_user_id=actor.id,
            action="admin.setting.cleared",
            target_type="setting",
            target_id=None,
            payload={"key": key, "scope": scope, "scope_id": str(scope_id) if scope_id else None},
        ))
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_settings_resolver.py -q
```

Expected: `10 passed`.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/services/settings/resolver.py \
        apps/backend/tests/test_settings_resolver.py
git commit -m "feat(admin): settings resolver (get/set/clear with type checks)"
```

---

### Task 9: Settings admin endpoints

**Files:**
- Create: `apps/backend/app/schemas/settings.py`
- Create: `apps/backend/app/routers/admin_settings.py`
- Modify: `apps/backend/app/main.py` (mount new router)
- Create: `apps/backend/tests/test_settings_admin_endpoints.py`

- [ ] **Step 1: Write the schemas**

`apps/backend/app/schemas/settings.py`:

```python
"""Pydantic schemas for settings endpoints."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class RegistryEntry(BaseModel):
    key: str
    type: str               # "bool" | "int" | "str" | "float"
    default: Any
    scopes: list[str]
    description: str
    public: bool


class SettingValueRead(BaseModel):
    key: str
    value: Any              # resolved value (or current at this layer)
    scope: str              # "global" | "household" | "user" | "default"
    scope_id: UUID | None = None


class SettingWrite(BaseModel):
    value: Any = Field(..., description="Type validated against the registry")


class GlobalSettingRow(BaseModel):
    key: str
    spec: RegistryEntry
    current_global: Any     # registry default if no override row exists
    has_global_override: bool
    household_override_count: int
    user_override_count: int


class SettingDetail(BaseModel):
    key: str
    spec: RegistryEntry
    current_global: Any
    has_global_override: bool
    household_overrides: list[dict]   # [{household_id, value, updated_at}]
    user_overrides: list[dict]        # [{user_id, value, updated_at}]
```

- [ ] **Step 2: Write the failing tests**

```python
# apps/backend/tests/test_settings_admin_endpoints.py
"""Admin settings endpoints — admin-only, all CRUD, all scopes."""
from fastapi.testclient import TestClient

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.main import app

client = TestClient(app)


def test_list_requires_admin(as_admin):
    r = client.get("/api/v1/admin/settings")
    assert r.status_code == 200
    keys = {row["key"] for row in r.json()}
    assert {"signups_open", "theme", "briefing_hour_local"} <= keys


def test_list_returns_override_counts(as_admin, db):
    from app.models.core import HouseholdSetting, UserSetting
    db.add(HouseholdSetting(household_id=DEV_HOUSEHOLD_ID, key="briefing_hour_local", value=9))
    db.add(UserSetting(user_id=DEV_USER_ID, key="theme", value="muted"))
    db.commit()
    r = client.get("/api/v1/admin/settings")
    rows = {row["key"]: row for row in r.json()}
    assert rows["briefing_hour_local"]["household_override_count"] == 1
    assert rows["theme"]["user_override_count"] == 1


def test_registry_endpoint(as_admin):
    r = client.get("/api/v1/admin/settings/registry")
    assert r.status_code == 200
    body = r.json()
    assert "signups_open" in body
    assert body["signups_open"]["type"] == "bool"


def test_set_global_then_get(as_admin):
    r = client.put("/api/v1/admin/settings/signups_open", json={"value": False})
    assert r.status_code == 204
    r = client.get("/api/v1/admin/settings/signups_open")
    assert r.status_code == 200
    body = r.json()
    assert body["current_global"] is False
    assert body["has_global_override"] is True


def test_set_global_type_mismatch_returns_422(as_admin):
    r = client.put("/api/v1/admin/settings/signups_open", json={"value": "yes"})
    assert r.status_code == 422


def test_set_household_override(as_admin):
    r = client.put(
        f"/api/v1/admin/settings/briefing_hour_local/household/{DEV_HOUSEHOLD_ID}",
        json={"value": 9},
    )
    assert r.status_code == 204
    r = client.get("/api/v1/admin/settings/briefing_hour_local")
    body = r.json()
    assert any(o["household_id"] == str(DEV_HOUSEHOLD_ID) and o["value"] == 9
               for o in body["household_overrides"])


def test_clear_global(as_admin):
    client.put("/api/v1/admin/settings/signups_open", json={"value": False})
    r = client.delete("/api/v1/admin/settings/signups_open")
    assert r.status_code == 204
    r = client.get("/api/v1/admin/settings/signups_open")
    body = r.json()
    assert body["has_global_override"] is False
    assert body["current_global"] is True  # registry default


def test_set_user_scoped_at_global_returns_422(as_admin):
    # `theme` is user-only; setting at global must fail
    r = client.put("/api/v1/admin/settings/theme", json={"value": "muted"})
    assert r.status_code == 422


def test_unknown_key_returns_404(as_admin):
    r = client.put("/api/v1/admin/settings/nonexistent", json={"value": 1})
    assert r.status_code == 404


def test_moderator_blocked():
    # Override to moderator; admin-only endpoint must 403
    from app.auth import get_current_user
    from app.main import app as _app
    from tests.conftest import MODERATOR_USER_ID, _override_as
    _app.dependency_overrides[get_current_user] = _override_as(MODERATOR_USER_ID)
    try:
        r = client.get("/api/v1/admin/settings")
        assert r.status_code == 403
    finally:
        _app.dependency_overrides.pop(get_current_user, None)


def test_unauthenticated_returns_401():
    from app.auth import get_current_user
    from app.main import app as _app
    # Remove the autouse override
    _app.dependency_overrides.pop(get_current_user, None)
    r = client.get("/api/v1/admin/settings")
    assert r.status_code == 401
```

- [ ] **Step 3: Run to confirm failure**

```bash
uv run pytest tests/test_settings_admin_endpoints.py -q
```

Expected: 404s on every endpoint (router not mounted).

- [ ] **Step 4: Create the router**

`apps/backend/app/routers/admin_settings.py`:

```python
"""Admin endpoints for app settings (3-layer)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import CurrentAdmin
from app.db import get_db
from app.models.core import (
    AppSettingKv, HouseholdSetting, UserSetting,
)
from app.schemas.settings import (
    GlobalSettingRow, RegistryEntry, SettingDetail, SettingWrite,
)
from app.services.settings.registry import SETTING_REGISTRY
from app.services.settings.resolver import clear_setting, get_setting, set_setting

router = APIRouter()


def _registry_entry(key: str) -> RegistryEntry:
    spec = SETTING_REGISTRY[key]
    return RegistryEntry(
        key=key, type=spec.type.__name__, default=spec.default,
        scopes=list(spec.scopes), description=spec.description, public=spec.public,
    )


def _require_known(key: str) -> None:
    if key not in SETTING_REGISTRY:
        raise HTTPException(status_code=404, detail=f"unknown setting key: {key}")


@router.get("", response_model=list[GlobalSettingRow])
def list_settings(_: CurrentAdmin, db: Session = Depends(get_db)):
    """List every registry setting with current global value + override counts."""
    rows = []
    # One query each for override counts (small N of registry keys)
    for key, spec in SETTING_REGISTRY.items():
        gl = db.get(AppSettingKv, key)
        hh_count = db.query(HouseholdSetting).filter_by(key=key).count()
        u_count = db.query(UserSetting).filter_by(key=key).count()
        rows.append(GlobalSettingRow(
            key=key,
            spec=_registry_entry(key),
            current_global=gl.value if gl is not None else spec.default,
            has_global_override=gl is not None,
            household_override_count=hh_count,
            user_override_count=u_count,
        ))
    return rows


@router.get("/registry", response_model=dict[str, RegistryEntry])
def get_registry(_: CurrentAdmin):
    return {k: _registry_entry(k) for k in SETTING_REGISTRY}


@router.get("/{key}", response_model=SettingDetail)
def get_setting_detail(key: str, _: CurrentAdmin, db: Session = Depends(get_db)):
    _require_known(key)
    spec = SETTING_REGISTRY[key]
    gl = db.get(AppSettingKv, key)
    hh = db.query(HouseholdSetting).filter_by(key=key).all()
    us = db.query(UserSetting).filter_by(key=key).all()
    return SettingDetail(
        key=key,
        spec=_registry_entry(key),
        current_global=gl.value if gl is not None else spec.default,
        has_global_override=gl is not None,
        household_overrides=[
            {"household_id": str(r.household_id), "value": r.value, "updated_at": r.updated_at.isoformat()}
            for r in hh
        ],
        user_overrides=[
            {"user_id": str(r.user_id), "value": r.value, "updated_at": r.updated_at.isoformat()}
            for r in us
        ],
    )


@router.put("/{key}", status_code=status.HTTP_204_NO_CONTENT)
def set_global(key: str, body: SettingWrite, user: CurrentAdmin, db: Session = Depends(get_db)):
    _require_known(key)
    try:
        set_setting(db, key, body.value, scope="global", scope_id=None, actor=user)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
def clear_global(key: str, user: CurrentAdmin, db: Session = Depends(get_db)):
    _require_known(key)
    clear_setting(db, key, scope="global", scope_id=None, actor=user)
    db.commit()


@router.put("/{key}/household/{hid}", status_code=status.HTTP_204_NO_CONTENT)
def set_household_override(
    key: str, hid: UUID, body: SettingWrite,
    user: CurrentAdmin, db: Session = Depends(get_db),
):
    _require_known(key)
    try:
        set_setting(db, key, body.value, scope="household", scope_id=hid, actor=user)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()


@router.delete("/{key}/household/{hid}", status_code=status.HTTP_204_NO_CONTENT)
def clear_household_override(key: str, hid: UUID, user: CurrentAdmin, db: Session = Depends(get_db)):
    _require_known(key)
    clear_setting(db, key, scope="household", scope_id=hid, actor=user)
    db.commit()


@router.put("/{key}/user/{uid}", status_code=status.HTTP_204_NO_CONTENT)
def set_user_override(
    key: str, uid: UUID, body: SettingWrite,
    user: CurrentAdmin, db: Session = Depends(get_db),
):
    _require_known(key)
    try:
        set_setting(db, key, body.value, scope="user", scope_id=uid, actor=user)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()


@router.delete("/{key}/user/{uid}", status_code=status.HTTP_204_NO_CONTENT)
def clear_user_override(key: str, uid: UUID, user: CurrentAdmin, db: Session = Depends(get_db)):
    _require_known(key)
    clear_setting(db, key, scope="user", scope_id=uid, actor=user)
    db.commit()
```

- [ ] **Step 5: Mount the router**

Edit `apps/backend/app/main.py`. After `from app.routers import …` line, add `admin_settings` to the import:

```python
from app.routers import (
    admin_settings, ai, auth, community, content, food, health, tracking,
)
```

After the existing `app.include_router(community.router, …)` line:

```python
# Admin (core)
app.include_router(admin_settings.router, prefix="/api/v1/admin/settings", tags=["admin"])
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/test_settings_admin_endpoints.py -q
```

Expected: `11 passed`.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/app/schemas/settings.py \
        apps/backend/app/routers/admin_settings.py \
        apps/backend/app/main.py \
        apps/backend/tests/test_settings_admin_endpoints.py
git commit -m "feat(admin): /admin/settings endpoints (list/registry/detail/CRUD)"
```

---

### Task 10: Self-service settings + public runtime-config

**Files:**
- Create: `apps/backend/app/routers/me_settings.py`
- Create: `apps/backend/app/routers/runtime_config.py`
- Modify: `apps/backend/app/main.py` (mount both)
- Create: `apps/backend/tests/test_settings_self_service_endpoints.py`
- Create: `apps/backend/tests/test_runtime_config_endpoint.py`

- [ ] **Step 1: Write failing tests for self-service**

```python
# apps/backend/tests/test_settings_self_service_endpoints.py
from fastapi.testclient import TestClient

from app.auth import DEV_HOUSEHOLD_ID
from app.main import app

client = TestClient(app)


def test_get_my_settings_returns_only_user_scoped_keys():
    r = client.get("/api/v1/me/settings")
    assert r.status_code == 200
    body = r.json()
    keys = {row["key"] for row in body}
    # theme + email_notifications + briefing_hour_local are all user-scoped
    assert {"theme", "email_notifications", "briefing_hour_local"} <= keys
    # signups_open is global-only — must NOT appear
    assert "signups_open" not in keys


def test_set_my_setting():
    r = client.put("/api/v1/me/settings/theme", json={"value": "muted"})
    assert r.status_code == 204
    r = client.get("/api/v1/me/settings")
    rows = {row["key"]: row["value"] for row in r.json()}
    assert rows["theme"] == "muted"


def test_clear_my_setting():
    client.put("/api/v1/me/settings/theme", json={"value": "muted"})
    r = client.delete("/api/v1/me/settings/theme")
    assert r.status_code == 204
    r = client.get("/api/v1/me/settings")
    rows = {row["key"]: row["value"] for row in r.json()}
    assert rows["theme"] == "warm"  # registry default


def test_set_non_user_scoped_key_returns_422():
    r = client.put("/api/v1/me/settings/signups_open", json={"value": False})
    assert r.status_code == 422


def test_household_settings_member_can_read():
    r = client.get(f"/api/v1/households/{DEV_HOUSEHOLD_ID}/settings")
    assert r.status_code == 200


def test_household_settings_owner_can_write():
    r = client.put(
        f"/api/v1/households/{DEV_HOUSEHOLD_ID}/settings/briefing_hour_local",
        json={"value": 9},
    )
    assert r.status_code == 204


def test_household_settings_non_member_returns_403(second_household):
    # DEV user isn't a member of second_household — write must 403
    r = client.put(
        f"/api/v1/households/{second_household.id}/settings/briefing_hour_local",
        json={"value": 9},
    )
    assert r.status_code == 403
```

- [ ] **Step 2: Write failing tests for runtime-config**

```python
# apps/backend/tests/test_runtime_config_endpoint.py
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_runtime_config_is_public():
    # Remove the autouse override to simulate unauthenticated
    from app.auth import get_current_user
    app.dependency_overrides.pop(get_current_user, None)
    r = client.get("/api/v1/runtime-config")
    assert r.status_code == 200


def test_runtime_config_returns_only_public_keys(as_admin):
    r = client.get("/api/v1/runtime-config")
    body = r.json()
    # signups_open and maintenance_message are public
    assert "signups_open" in body
    assert "maintenance_message" in body
    # llm_cli_concurrency is not public
    assert "llm_cli_concurrency" not in body
    # theme is user-scoped, not global+public
    assert "theme" not in body


def test_runtime_config_reflects_global_setting(as_admin):
    client.put("/api/v1/admin/settings/signups_open", json={"value": False})
    r = client.get("/api/v1/runtime-config")
    assert r.json()["signups_open"] is False
```

- [ ] **Step 3: Run tests to confirm failure**

```bash
uv run pytest tests/test_settings_self_service_endpoints.py tests/test_runtime_config_endpoint.py -q
```

Expected: 404 on every endpoint.

- [ ] **Step 4: Create `me_settings.py` router**

`apps/backend/app/routers/me_settings.py`:

```python
"""Self-service settings: /me/settings/* and /households/{id}/settings/*."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import CurrentHousehold, CurrentUser
from app.db import get_db
from app.models.core import HouseholdMember, UserSetting, HouseholdSetting
from app.schemas.settings import SettingValueRead, SettingWrite
from app.services.settings.registry import SETTING_REGISTRY
from app.services.settings.resolver import clear_setting, get_setting, set_setting

router = APIRouter()


# --- /me/settings ---

@router.get("/me/settings", response_model=list[SettingValueRead])
def list_my_settings(user: CurrentUser, db: Session = Depends(get_db)):
    """Return every user-scoped setting with the resolved value for *this user*."""
    out = []
    for key, spec in SETTING_REGISTRY.items():
        if "user" not in spec.scopes:
            continue
        out.append(SettingValueRead(
            key=key, value=get_setting(db, key, user=user),
            scope="user", scope_id=user.id,
        ))
    return out


@router.put("/me/settings/{key}", status_code=status.HTTP_204_NO_CONTENT)
def set_my_setting(
    key: str, body: SettingWrite, user: CurrentUser, db: Session = Depends(get_db),
):
    if key not in SETTING_REGISTRY:
        raise HTTPException(status_code=404, detail="unknown setting key")
    try:
        set_setting(db, key, body.value, scope="user", scope_id=user.id, actor=user)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()


@router.delete("/me/settings/{key}", status_code=status.HTTP_204_NO_CONTENT)
def clear_my_setting(key: str, user: CurrentUser, db: Session = Depends(get_db)):
    if key not in SETTING_REGISTRY:
        raise HTTPException(status_code=404, detail="unknown setting key")
    clear_setting(db, key, scope="user", scope_id=user.id, actor=user)
    db.commit()


# --- /households/{hid}/settings ---

def _require_member(db: Session, user_id, household_id) -> HouseholdMember:
    m = (
        db.query(HouseholdMember)
        .filter_by(user_id=user_id, household_id=household_id)
        .one_or_none()
    )
    if m is None:
        raise HTTPException(status_code=403, detail="not a member of this household")
    return m


def _require_owner(db: Session, user_id, household_id) -> None:
    m = _require_member(db, user_id, household_id)
    if m.role != "owner":
        raise HTTPException(status_code=403, detail="household owner role required")


@router.get("/households/{hid}/settings", response_model=list[SettingValueRead])
def list_household_settings(
    hid: UUID, user: CurrentUser, db: Session = Depends(get_db),
):
    from app.models.core import Household
    _require_member(db, user.id, hid)
    hh = db.get(Household, hid)
    out = []
    for key, spec in SETTING_REGISTRY.items():
        if "household" not in spec.scopes:
            continue
        out.append(SettingValueRead(
            key=key, value=get_setting(db, key, household=hh),
            scope="household", scope_id=hid,
        ))
    return out


@router.put("/households/{hid}/settings/{key}", status_code=status.HTTP_204_NO_CONTENT)
def set_household_setting(
    hid: UUID, key: str, body: SettingWrite,
    user: CurrentUser, db: Session = Depends(get_db),
):
    if key not in SETTING_REGISTRY:
        raise HTTPException(status_code=404, detail="unknown setting key")
    _require_owner(db, user.id, hid)
    try:
        set_setting(db, key, body.value, scope="household", scope_id=hid, actor=user)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    db.commit()


@router.delete("/households/{hid}/settings/{key}", status_code=status.HTTP_204_NO_CONTENT)
def clear_household_setting(
    hid: UUID, key: str, user: CurrentUser, db: Session = Depends(get_db),
):
    if key not in SETTING_REGISTRY:
        raise HTTPException(status_code=404, detail="unknown setting key")
    _require_owner(db, user.id, hid)
    clear_setting(db, key, scope="household", scope_id=hid, actor=user)
    db.commit()
```

- [ ] **Step 5: Create `runtime_config.py` router**

`apps/backend/app/routers/runtime_config.py`:

```python
"""Public runtime configuration. No auth. Returns whitelisted globals only."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.core import AppSettingKv
from app.services.settings.registry import SETTING_REGISTRY

router = APIRouter()


@router.get("", response_model=dict[str, Any])
def get_runtime_config(db: Session = Depends(get_db)):
    out: dict[str, Any] = {}
    for key, spec in SETTING_REGISTRY.items():
        if not spec.public:
            continue
        row = db.get(AppSettingKv, key)
        out[key] = row.value if row is not None else spec.default
    return out
```

- [ ] **Step 6: Mount both routers**

In `apps/backend/app/main.py`, extend the imports:

```python
from app.routers import (
    admin_settings, ai, auth, community, content, food, health,
    me_settings, runtime_config, tracking,
)
```

After the existing `admin_settings` mount:

```python
app.include_router(me_settings.router, prefix="/api/v1", tags=["me"])
app.include_router(runtime_config.router, prefix="/api/v1/runtime-config", tags=["public"])
```

- [ ] **Step 7: Run all the new tests**

```bash
uv run pytest tests/test_settings_self_service_endpoints.py tests/test_runtime_config_endpoint.py -q
```

Expected: `10 passed`.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/app/routers/me_settings.py \
        apps/backend/app/routers/runtime_config.py \
        apps/backend/app/main.py \
        apps/backend/tests/test_settings_self_service_endpoints.py \
        apps/backend/tests/test_runtime_config_endpoint.py
git commit -m "feat(admin): self-service /me/settings + /households/{id}/settings + public /runtime-config"
```

---

## Phase 3 — Feature flags backend

### Task 11: Flags resolver

**Files:**
- Create: `apps/backend/app/services/flags/__init__.py` (empty)
- Create: `apps/backend/app/services/flags/resolver.py`
- Create: `apps/backend/tests/test_flags_resolver.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/test_flags_resolver.py
"""is_enabled: user > household > global > rollout_percent > default off."""
from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.core import (
    FeatureFlag, FeatureFlagOverride, Household, User,
)
from app.services.flags.resolver import is_enabled


def _flag(db, key, *, enabled_globally=False, rollout=0):
    db.add(FeatureFlag(key=key, enabled_globally=enabled_globally, rollout_percent=rollout))
    db.flush()


def test_unknown_flag_returns_false(db):
    user = db.get(User, DEV_USER_ID)
    assert is_enabled(db, "nonexistent", user=user) is False


def test_global_enabled(db):
    user = db.get(User, DEV_USER_ID)
    _flag(db, "ff.simple", enabled_globally=True)
    assert is_enabled(db, "ff.simple", user=user) is True


def test_user_override_beats_global(db):
    user = db.get(User, DEV_USER_ID)
    _flag(db, "ff.user_off", enabled_globally=True)
    db.add(FeatureFlagOverride(flag_key="ff.user_off", user_id=user.id, enabled=False))
    db.flush()
    assert is_enabled(db, "ff.user_off", user=user) is False


def test_household_override_beats_global(db):
    hh = db.get(Household, DEV_HOUSEHOLD_ID)
    _flag(db, "ff.hh_on", enabled_globally=False)
    db.add(FeatureFlagOverride(flag_key="ff.hh_on", household_id=hh.id, enabled=True))
    db.flush()
    assert is_enabled(db, "ff.hh_on", household=hh) is True


def test_user_override_beats_household_override(db):
    user = db.get(User, DEV_USER_ID)
    hh = db.get(Household, DEV_HOUSEHOLD_ID)
    _flag(db, "ff.stack")
    db.add(FeatureFlagOverride(flag_key="ff.stack", household_id=hh.id, enabled=True))
    db.add(FeatureFlagOverride(flag_key="ff.stack", user_id=user.id, enabled=False))
    db.flush()
    assert is_enabled(db, "ff.stack", user=user, household=hh) is False


def test_rollout_percent_is_deterministic(db):
    user = db.get(User, DEV_USER_ID)
    _flag(db, "ff.rolling", enabled_globally=False, rollout=50)
    a = is_enabled(db, "ff.rolling", user=user)
    b = is_enabled(db, "ff.rolling", user=user)
    assert a == b


def test_rollout_zero_is_off(db):
    user = db.get(User, DEV_USER_ID)
    _flag(db, "ff.zero", enabled_globally=False, rollout=0)
    assert is_enabled(db, "ff.zero", user=user) is False


def test_rollout_100_is_on(db):
    user = db.get(User, DEV_USER_ID)
    _flag(db, "ff.full", enabled_globally=False, rollout=100)
    assert is_enabled(db, "ff.full", user=user) is True


def test_rollout_ignored_without_user(db):
    _flag(db, "ff.anon", enabled_globally=False, rollout=100)
    assert is_enabled(db, "ff.anon") is False  # no user, rollout ignored


def test_deleted_flag_returns_false(db):
    from datetime import datetime, timezone
    user = db.get(User, DEV_USER_ID)
    db.add(FeatureFlag(
        key="ff.gone", enabled_globally=True,
        deleted_at=datetime.now(timezone.utc),
    ))
    db.flush()
    assert is_enabled(db, "ff.gone", user=user) is False
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd apps/backend
uv run pytest tests/test_flags_resolver.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.services.flags.resolver'`.

- [ ] **Step 3: Create the resolver**

`apps/backend/app/services/flags/__init__.py`: empty file.

`apps/backend/app/services/flags/resolver.py`:

```python
"""Feature-flag resolver. user override > household override > enabled_globally > rollout > off."""
from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session as DbSession

from app.models.core import FeatureFlag, FeatureFlagOverride, Household, User


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
        return False

    if user:
        ov = (
            db.query(FeatureFlagOverride)
            .filter_by(flag_key=key, user_id=user.id)
            .first()
        )
        if ov is not None:
            return ov.enabled

    if household:
        ov = (
            db.query(FeatureFlagOverride)
            .filter_by(flag_key=key, household_id=household.id)
            .first()
        )
        if ov is not None:
            return ov.enabled

    if flag.enabled_globally:
        return True

    if flag.rollout_percent > 0 and user is not None:
        h = int(hashlib.sha256(f"{key}:{user.id}".encode()).hexdigest()[:8], 16)
        return (h % 100) < flag.rollout_percent

    return False
```

- [ ] **Step 4: Run tests to pass**

```bash
uv run pytest tests/test_flags_resolver.py -q
```

Expected: `10 passed`.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/services/flags/__init__.py \
        apps/backend/app/services/flags/resolver.py \
        apps/backend/tests/test_flags_resolver.py
git commit -m "feat(admin): feature-flag resolver (3-layer + rollout-percent hash)"
```

---

### Task 12: Flags admin endpoints + initial seeded flags

**Files:**
- Create: `apps/backend/app/schemas/flags.py`
- Create: `apps/backend/app/services/flags/admin.py` (service helpers + seeding)
- Create: `apps/backend/app/routers/admin_flags.py`
- Modify: `apps/backend/app/auth.py` (seed initial flags in seed_reference_data)
- Modify: `apps/backend/app/main.py` (mount router)
- Create: `apps/backend/tests/test_flags_admin_endpoints.py`

- [ ] **Step 1: Write the schemas**

`apps/backend/app/schemas/flags.py`:

```python
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class FeatureFlagRead(BaseModel):
    key: str
    description: str | None
    enabled_globally: bool
    rollout_percent: int
    household_override_count: int = 0
    user_override_count: int = 0


class FeatureFlagCreate(BaseModel):
    key: str = Field(..., min_length=3, max_length=120)
    description: str | None = None
    enabled_globally: bool = False
    rollout_percent: int = Field(0, ge=0, le=100)


class FeatureFlagPatch(BaseModel):
    description: str | None = None
    enabled_globally: bool | None = None
    rollout_percent: int | None = Field(None, ge=0, le=100)


class OverrideWrite(BaseModel):
    enabled: bool


class OverrideRead(BaseModel):
    id: UUID
    flag_key: str
    household_id: UUID | None
    user_id: UUID | None
    enabled: bool
    created_at: datetime
```

- [ ] **Step 2: Create the admin helpers + seeding**

`apps/backend/app/services/flags/admin.py`:

```python
"""Service helpers for flag admin endpoints + the startup seeder."""
from __future__ import annotations

from sqlalchemy.orm import Session as DbSession

from app.models.core import AuditLog, FeatureFlag, FeatureFlagOverride, User


INITIAL_FLAGS: list[dict] = [
    {"key": "community.exchange_engine.enabled", "enabled_globally": False,
     "description": "Phase 3 exchange engine — dark launch"},
    {"key": "ai.opus_meal_planner.enabled", "enabled_globally": True,
     "description": "Kill-switch for Opus-backed meal planning"},
    {"key": "content.youtube_ingestion.enabled", "enabled_globally": True,
     "description": "Kill-switch for YouTube content enrichment"},
    {"key": "voice.assistant.enabled", "enabled_globally": False,
     "description": "Voice assistant launch gate"},
]


def seed_initial_flags(db: DbSession) -> None:
    """Idempotent seed of the initial flags. Safe to call on every startup."""
    for spec in INITIAL_FLAGS:
        exists = db.query(FeatureFlag).filter_by(key=spec["key"]).one_or_none()
        if exists is None:
            db.add(FeatureFlag(**spec))


def set_household_override(
    db: DbSession, *, flag_key: str, household_id, enabled: bool, actor: User,
) -> FeatureFlagOverride:
    row = (
        db.query(FeatureFlagOverride)
        .filter_by(flag_key=flag_key, household_id=household_id, user_id=None)
        .one_or_none()
    )
    if row is None:
        row = FeatureFlagOverride(
            flag_key=flag_key, household_id=household_id, enabled=enabled,
            created_by_user_id=actor.id,
        )
        db.add(row)
    else:
        row.enabled = enabled
    db.add(AuditLog(
        actor_user_id=actor.id, action="admin.flag.override_set",
        target_type="feature_flag", target_id=None,
        payload={"flag_key": flag_key, "household_id": str(household_id), "enabled": enabled},
    ))
    return row


def set_user_override(
    db: DbSession, *, flag_key: str, user_id, enabled: bool, actor: User,
) -> FeatureFlagOverride:
    row = (
        db.query(FeatureFlagOverride)
        .filter_by(flag_key=flag_key, user_id=user_id, household_id=None)
        .one_or_none()
    )
    if row is None:
        row = FeatureFlagOverride(
            flag_key=flag_key, user_id=user_id, enabled=enabled,
            created_by_user_id=actor.id,
        )
        db.add(row)
    else:
        row.enabled = enabled
    db.add(AuditLog(
        actor_user_id=actor.id, action="admin.flag.override_set",
        target_type="feature_flag", target_id=None,
        payload={"flag_key": flag_key, "user_id": str(user_id), "enabled": enabled},
    ))
    return row


def clear_household_override(db: DbSession, *, flag_key: str, household_id, actor: User) -> None:
    row = (
        db.query(FeatureFlagOverride)
        .filter_by(flag_key=flag_key, household_id=household_id, user_id=None)
        .one_or_none()
    )
    if row is not None:
        db.delete(row)
        db.add(AuditLog(
            actor_user_id=actor.id, action="admin.flag.override_cleared",
            target_type="feature_flag", target_id=None,
            payload={"flag_key": flag_key, "household_id": str(household_id)},
        ))


def clear_user_override(db: DbSession, *, flag_key: str, user_id, actor: User) -> None:
    row = (
        db.query(FeatureFlagOverride)
        .filter_by(flag_key=flag_key, user_id=user_id, household_id=None)
        .one_or_none()
    )
    if row is not None:
        db.delete(row)
        db.add(AuditLog(
            actor_user_id=actor.id, action="admin.flag.override_cleared",
            target_type="feature_flag", target_id=None,
            payload={"flag_key": flag_key, "user_id": str(user_id)},
        ))
```

- [ ] **Step 3: Wire `seed_initial_flags` into `seed_reference_data`**

Edit `apps/backend/app/auth.py`, in `seed_reference_data`:

```python
from app.services.flags.admin import seed_initial_flags

def seed_reference_data(db: DbSession) -> None:
    seed_starter_ingredients(db)
    seed_badge_definitions(db)
    seed_initial_flags(db)
    bootstrap_admin(
        db,
        email=settings.admin_email,
        password=settings.admin_password,
        display_name=settings.admin_display_name,
    )
```

- [ ] **Step 4: Write failing tests for the admin endpoints**

```python
# apps/backend/tests/test_flags_admin_endpoints.py
from fastapi.testclient import TestClient

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.main import app

client = TestClient(app)


def test_list_includes_seeded_flags(as_admin):
    r = client.get("/api/v1/admin/flags")
    assert r.status_code == 200
    keys = {row["key"] for row in r.json()}
    assert "community.exchange_engine.enabled" in keys
    assert "ai.opus_meal_planner.enabled" in keys


def test_create_flag(as_admin):
    r = client.post("/api/v1/admin/flags", json={
        "key": "test.new_flag", "description": "x", "enabled_globally": True,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["key"] == "test.new_flag"
    assert body["enabled_globally"] is True


def test_create_flag_duplicate_returns_409(as_admin):
    client.post("/api/v1/admin/flags", json={"key": "dup.flag"})
    r = client.post("/api/v1/admin/flags", json={"key": "dup.flag"})
    assert r.status_code == 409


def test_patch_flag(as_admin):
    client.post("/api/v1/admin/flags", json={"key": "patch.flag"})
    r = client.patch("/api/v1/admin/flags/patch.flag", json={
        "enabled_globally": True, "rollout_percent": 25,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["enabled_globally"] is True
    assert body["rollout_percent"] == 25


def test_soft_delete_flag(as_admin):
    client.post("/api/v1/admin/flags", json={"key": "delete.flag"})
    r = client.delete("/api/v1/admin/flags/delete.flag")
    assert r.status_code == 204
    # Re-fetch — flag is gone from list (deleted_at filter)
    r = client.get("/api/v1/admin/flags")
    keys = {row["key"] for row in r.json()}
    assert "delete.flag" not in keys


def test_set_household_override(as_admin):
    client.post("/api/v1/admin/flags", json={"key": "hh.over"})
    r = client.put(
        f"/api/v1/admin/flags/hh.over/household/{DEV_HOUSEHOLD_ID}",
        json={"enabled": True},
    )
    assert r.status_code == 204
    r = client.get("/api/v1/admin/flags/hh.over")
    body = r.json()
    assert any(o["household_id"] == str(DEV_HOUSEHOLD_ID) and o["enabled"] is True
               for o in body["household_overrides"])


def test_set_user_override(as_admin):
    client.post("/api/v1/admin/flags", json={"key": "u.over"})
    r = client.put(
        f"/api/v1/admin/flags/u.over/user/{DEV_USER_ID}",
        json={"enabled": True},
    )
    assert r.status_code == 204


def test_clear_household_override(as_admin):
    client.post("/api/v1/admin/flags", json={"key": "clear.hh"})
    client.put(
        f"/api/v1/admin/flags/clear.hh/household/{DEV_HOUSEHOLD_ID}",
        json={"enabled": True},
    )
    r = client.delete(f"/api/v1/admin/flags/clear.hh/household/{DEV_HOUSEHOLD_ID}")
    assert r.status_code == 204


def test_moderator_blocked():
    from app.auth import get_current_user
    from app.main import app as _app
    from tests.conftest import MODERATOR_USER_ID, _override_as
    _app.dependency_overrides[get_current_user] = _override_as(MODERATOR_USER_ID)
    try:
        r = client.get("/api/v1/admin/flags")
        assert r.status_code == 403
    finally:
        _app.dependency_overrides.pop(get_current_user, None)
```

- [ ] **Step 5: Create the router**

`apps/backend/app/routers/admin_flags.py`:

```python
"""Admin endpoints for feature flags + per-household / per-user overrides."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import CurrentAdmin
from app.db import get_db
from app.models.core import (
    AuditLog, FeatureFlag, FeatureFlagOverride,
)
from app.schemas.flags import (
    FeatureFlagCreate, FeatureFlagPatch, FeatureFlagRead, OverrideWrite,
)
from app.services.flags.admin import (
    clear_household_override, clear_user_override,
    set_household_override, set_user_override,
)

router = APIRouter()


def _flag_or_404(db: Session, key: str) -> FeatureFlag:
    f = (
        db.query(FeatureFlag)
        .filter(FeatureFlag.key == key, FeatureFlag.deleted_at.is_(None))
        .one_or_none()
    )
    if f is None:
        raise HTTPException(status_code=404, detail="flag not found")
    return f


def _read(db: Session, f: FeatureFlag) -> FeatureFlagRead:
    hh_count = (
        db.query(FeatureFlagOverride)
        .filter_by(flag_key=f.key)
        .filter(FeatureFlagOverride.household_id.isnot(None))
        .count()
    )
    u_count = (
        db.query(FeatureFlagOverride)
        .filter_by(flag_key=f.key)
        .filter(FeatureFlagOverride.user_id.isnot(None))
        .count()
    )
    return FeatureFlagRead(
        key=f.key, description=f.description,
        enabled_globally=f.enabled_globally, rollout_percent=f.rollout_percent,
        household_override_count=hh_count, user_override_count=u_count,
    )


@router.get("", response_model=list[FeatureFlagRead])
def list_flags(_: CurrentAdmin, db: Session = Depends(get_db)):
    flags = (
        db.query(FeatureFlag)
        .filter(FeatureFlag.deleted_at.is_(None))
        .order_by(FeatureFlag.key)
        .all()
    )
    return [_read(db, f) for f in flags]


@router.post("", response_model=FeatureFlagRead, status_code=status.HTTP_201_CREATED)
def create_flag(body: FeatureFlagCreate, _: CurrentAdmin, db: Session = Depends(get_db)):
    f = FeatureFlag(
        key=body.key, description=body.description,
        enabled_globally=body.enabled_globally, rollout_percent=body.rollout_percent,
    )
    db.add(f)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="flag key already exists")
    return _read(db, f)


@router.get("/{key}")
def get_flag(key: str, _: CurrentAdmin, db: Session = Depends(get_db)):
    f = _flag_or_404(db, key)
    overrides = db.query(FeatureFlagOverride).filter_by(flag_key=key).all()
    return {
        **_read(db, f).model_dump(),
        "household_overrides": [
            {"id": str(o.id), "household_id": str(o.household_id), "enabled": o.enabled}
            for o in overrides if o.household_id is not None
        ],
        "user_overrides": [
            {"id": str(o.id), "user_id": str(o.user_id), "enabled": o.enabled}
            for o in overrides if o.user_id is not None
        ],
    }


@router.patch("/{key}", response_model=FeatureFlagRead)
def patch_flag(
    key: str, body: FeatureFlagPatch, user: CurrentAdmin, db: Session = Depends(get_db),
):
    f = _flag_or_404(db, key)
    changes: dict = {}
    if body.description is not None:
        f.description = body.description
        changes["description"] = body.description
    if body.enabled_globally is not None:
        f.enabled_globally = body.enabled_globally
        changes["enabled_globally"] = body.enabled_globally
    if body.rollout_percent is not None:
        f.rollout_percent = body.rollout_percent
        changes["rollout_percent"] = body.rollout_percent
    db.add(AuditLog(
        actor_user_id=user.id, action="admin.flag.updated",
        target_type="feature_flag", target_id=None,
        payload={"key": key, **changes},
    ))
    db.commit()
    return _read(db, f)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_flag(key: str, user: CurrentAdmin, db: Session = Depends(get_db)):
    f = _flag_or_404(db, key)
    f.deleted_at = datetime.now(timezone.utc)
    db.add(AuditLog(
        actor_user_id=user.id, action="admin.flag.deleted",
        target_type="feature_flag", target_id=None,
        payload={"key": key},
    ))
    db.commit()


@router.put("/{key}/household/{hid}", status_code=status.HTTP_204_NO_CONTENT)
def put_household_override(
    key: str, hid: UUID, body: OverrideWrite,
    user: CurrentAdmin, db: Session = Depends(get_db),
):
    _flag_or_404(db, key)
    set_household_override(db, flag_key=key, household_id=hid, enabled=body.enabled, actor=user)
    db.commit()


@router.delete("/{key}/household/{hid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_household_override(
    key: str, hid: UUID, user: CurrentAdmin, db: Session = Depends(get_db),
):
    clear_household_override(db, flag_key=key, household_id=hid, actor=user)
    db.commit()


@router.put("/{key}/user/{uid}", status_code=status.HTTP_204_NO_CONTENT)
def put_user_override(
    key: str, uid: UUID, body: OverrideWrite,
    user: CurrentAdmin, db: Session = Depends(get_db),
):
    _flag_or_404(db, key)
    set_user_override(db, flag_key=key, user_id=uid, enabled=body.enabled, actor=user)
    db.commit()


@router.delete("/{key}/user/{uid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user_override(
    key: str, uid: UUID, user: CurrentAdmin, db: Session = Depends(get_db),
):
    clear_user_override(db, flag_key=key, user_id=uid, actor=user)
    db.commit()
```

- [ ] **Step 6: Mount the router**

In `apps/backend/app/main.py`, extend imports:

```python
from app.routers import (
    admin_flags, admin_settings, ai, auth, community, content, food, health,
    me_settings, runtime_config, tracking,
)
```

And after `admin_settings` mount:

```python
app.include_router(admin_flags.router, prefix="/api/v1/admin/flags", tags=["admin"])
```

- [ ] **Step 7: Wipe new tables in conftest**

In `apps/backend/tests/conftest.py`, inside `_clean_household_data`, add (alongside the other Phase-2 wipes):

```python
        from app.models.core import FeatureFlag
        # Wipe non-seeded flags between tests; the seeded ones are restored on next startup.
        db_.query(FeatureFlag).filter(
            ~FeatureFlag.key.in_([
                "community.exchange_engine.enabled",
                "ai.opus_meal_planner.enabled",
                "content.youtube_ingestion.enabled",
                "voice.assistant.enabled",
            ])
        ).delete(synchronize_session=False)
```

Note: the `FeatureFlagOverride` wipe is already in place from Task 6.

- [ ] **Step 8: Run tests**

```bash
uv run pytest tests/test_flags_admin_endpoints.py -q
```

Expected: `9 passed`.

- [ ] **Step 9: Verify seeded flags appear on a fresh startup**

```bash
uv run pytest tests/test_flags_admin_endpoints.py::test_list_includes_seeded_flags -v
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add apps/backend/app/schemas/flags.py \
        apps/backend/app/services/flags/admin.py \
        apps/backend/app/routers/admin_flags.py \
        apps/backend/app/auth.py \
        apps/backend/app/main.py \
        apps/backend/tests/conftest.py \
        apps/backend/tests/test_flags_admin_endpoints.py
git commit -m "feat(admin): /admin/flags endpoints + initial seeded flags"
```

---

## Phase 4 — Moderation backend

### Task 13: Admin user-management endpoints

**Files:**
- Create: `apps/backend/app/schemas/admin.py`
- Create: `apps/backend/app/services/admin/users.py`
- Create: `apps/backend/app/routers/admin_users.py`
- Modify: `apps/backend/app/main.py` (mount)
- Create: `apps/backend/tests/test_user_management_endpoints.py`

- [ ] **Step 1: Write the schemas**

`apps/backend/app/schemas/admin.py`:

```python
"""Pydantic schemas shared across admin endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ModerationReason(BaseModel):
    """Mixin for moderator-grade writes — every such write requires a non-empty reason."""
    reason: str = Field(..., min_length=3, max_length=500)


class UserListRow(BaseModel):
    id: UUID
    email: str
    display_name: str | None
    role: str
    is_active: bool
    locked_until: datetime | None
    created_at: datetime


class UserDetail(UserListRow):
    household_memberships: list[dict]
    listing_count: int = 0


class RolePatch(BaseModel):
    role: Literal["user", "moderator", "admin"]


class IsActivePatch(ModerationReason):
    is_active: bool


class LockBody(ModerationReason):
    hours: int = Field(..., ge=1, le=720)  # 1 hour to 30 days
```

- [ ] **Step 2: Write service helpers**

`apps/backend/app/services/admin/users.py`:

```python
"""Service helpers for admin user-management endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session as DbSession

from app.models.core import AuditLog, Event, User
from app.services.auth.permissions import assert_not_last_admin


def change_role(db: DbSession, *, target: User, new_role: str, actor: User) -> None:
    if new_role == target.role:
        return
    if target.role == "admin" and new_role != "admin":
        assert_not_last_admin(db, target)
    old = target.role
    target.role = new_role
    db.add(AuditLog(
        actor_user_id=actor.id, action="admin.user.role_changed",
        target_type="user", target_id=target.id,
        payload={"from": old, "to": new_role},
    ))
    db.add(Event(
        user_id=actor.id, event_type="admin.user.role_changed",
        entity_type="user", entity_id=target.id,
        payload={"from": old, "to": new_role},
    ))


def set_active(db: DbSession, *, target: User, is_active: bool, reason: str, actor: User) -> None:
    if is_active == target.is_active:
        return
    if not is_active and target.role == "admin":
        assert_not_last_admin(db, target)
    target.is_active = is_active
    action = "admin.user.activated" if is_active else "admin.user.deactivated"
    db.add(AuditLog(
        actor_user_id=actor.id, action=action,
        target_type="user", target_id=target.id,
        payload={"reason": reason},
    ))
    db.add(Event(
        user_id=actor.id, event_type=action,
        entity_type="user", entity_id=target.id,
        payload={"reason": reason},
    ))


def lock_user(db: DbSession, *, target: User, hours: int, reason: str, actor: User) -> None:
    target.locked_until = datetime.now(timezone.utc) + timedelta(hours=hours)
    db.add(AuditLog(
        actor_user_id=actor.id, action="admin.user.locked",
        target_type="user", target_id=target.id,
        payload={"reason": reason, "hours": hours},
    ))
    db.add(Event(
        user_id=actor.id, event_type="admin.user.locked",
        entity_type="user", entity_id=target.id,
        payload={"reason": reason, "hours": hours},
    ))


def unlock_user(db: DbSession, *, target: User, reason: str, actor: User) -> None:
    target.locked_until = None
    db.add(AuditLog(
        actor_user_id=actor.id, action="admin.user.unlocked",
        target_type="user", target_id=target.id,
        payload={"reason": reason},
    ))
    db.add(Event(
        user_id=actor.id, event_type="admin.user.unlocked",
        entity_type="user", entity_id=target.id,
        payload={"reason": reason},
    ))
```

- [ ] **Step 3: Write failing endpoint tests**

```python
# apps/backend/tests/test_user_management_endpoints.py
from fastapi.testclient import TestClient

from app.auth import DEV_USER_ID
from app.main import app
from tests.conftest import ADMIN_USER_ID, MODERATOR_USER_ID

client = TestClient(app)


def test_list_users_admin(as_admin):
    r = client.get("/api/v1/admin/users")
    assert r.status_code == 200
    emails = {row["email"] for row in r.json()}
    assert "admin@frugal-living.local" in emails
    assert "moderator@frugal-living.local" in emails


def test_list_users_moderator(as_moderator):
    r = client.get("/api/v1/admin/users")
    assert r.status_code == 200  # moderators can read user list


def test_list_users_regular_user_403():
    r = client.get("/api/v1/admin/users")
    assert r.status_code == 403


def test_get_user_detail(as_admin):
    r = client.get(f"/api/v1/admin/users/{DEV_USER_ID}")
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "dev@frugal-living.local"


def test_patch_role_admin_only(as_admin):
    r = client.patch(f"/api/v1/admin/users/{DEV_USER_ID}", json={"role": "moderator"})
    assert r.status_code == 200
    # Revert so other tests still see DEV_USER as 'user'
    client.patch(f"/api/v1/admin/users/{DEV_USER_ID}", json={"role": "user"})


def test_patch_role_moderator_blocked(as_moderator):
    r = client.patch(f"/api/v1/admin/users/{DEV_USER_ID}", json={"role": "moderator"})
    # Moderator cannot change roles — body shape requires admin
    assert r.status_code == 403


def test_patch_is_active_moderator_can(as_moderator):
    r = client.patch(
        f"/api/v1/admin/users/{DEV_USER_ID}",
        json={"is_active": False, "reason": "spam reports"},
    )
    assert r.status_code == 200
    # Revert
    client.patch(
        f"/api/v1/admin/users/{DEV_USER_ID}",
        json={"is_active": True, "reason": "appeal granted"},
    )


def test_patch_is_active_requires_reason(as_moderator):
    r = client.patch(f"/api/v1/admin/users/{DEV_USER_ID}", json={"is_active": False})
    assert r.status_code == 422  # reason missing


def test_last_admin_guard(as_admin):
    # Admin user (fixture) is the only active admin — demoting must 400
    r = client.patch(f"/api/v1/admin/users/{ADMIN_USER_ID}", json={"role": "user"})
    assert r.status_code == 400
    assert "last active admin" in r.json()["detail"]


def test_lock_unlock_round_trip(as_moderator):
    r = client.post(
        f"/api/v1/admin/users/{DEV_USER_ID}/lock",
        json={"reason": "cool-off", "hours": 2},
    )
    assert r.status_code == 204
    r = client.get(f"/api/v1/admin/users/{DEV_USER_ID}")
    assert r.json()["locked_until"] is not None
    r = client.post(
        f"/api/v1/admin/users/{DEV_USER_ID}/unlock",
        json={"reason": "manual review passed"},
    )
    assert r.status_code == 204
    r = client.get(f"/api/v1/admin/users/{DEV_USER_ID}")
    assert r.json()["locked_until"] is None


def test_audit_log_written_on_lock(as_moderator, db):
    from app.models.core import AuditLog
    client.post(
        f"/api/v1/admin/users/{DEV_USER_ID}/lock",
        json={"reason": "test", "hours": 1},
    )
    rows = db.query(AuditLog).filter_by(action="admin.user.locked").all()
    assert any(r.payload.get("reason") == "test" for r in rows)


def test_search_by_email(as_admin):
    r = client.get("/api/v1/admin/users?q=moderator")
    emails = {row["email"] for row in r.json()}
    assert "moderator@frugal-living.local" in emails
    assert "dev@frugal-living.local" not in emails
```

- [ ] **Step 4: Run to confirm failure**

```bash
cd apps/backend
uv run pytest tests/test_user_management_endpoints.py -q
```

Expected: 404 on every endpoint.

- [ ] **Step 5: Create the router**

`apps/backend/app/routers/admin_users.py`:

```python
"""/api/v1/admin/users — list/detail/role/active/lock/unlock."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import CurrentAdmin, CurrentModerator, CurrentUser
from app.db import get_db
from app.models.core import HouseholdMember, User
from app.models.community import Listing
from app.schemas.admin import (
    IsActivePatch, LockBody, ModerationReason, RolePatch,
    UserDetail, UserListRow,
)
from app.services.admin.users import change_role, lock_user, set_active, unlock_user
from app.services.auth.permissions import is_admin, is_at_least_moderator

router = APIRouter()


def _row(u: User) -> UserListRow:
    return UserListRow(
        id=u.id, email=u.email, display_name=u.display_name,
        role=u.role, is_active=u.is_active, locked_until=u.locked_until,
        created_at=u.created_at,
    )


@router.get("", response_model=list[UserListRow])
def list_users(
    _: CurrentModerator,
    db: Session = Depends(get_db),
    q: str | None = Query(None, description="case-insensitive substring on email"),
    role: str | None = Query(None),
    active: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    query = db.query(User)
    if q:
        query = query.filter(User.email.ilike(f"%{q}%"))
    if role:
        query = query.filter(User.role == role)
    if active is not None:
        query = query.filter(User.is_active.is_(active))
    rows = query.order_by(User.created_at.desc()).offset(offset).limit(limit).all()
    return [_row(u) for u in rows]


@router.get("/{user_id}", response_model=UserDetail)
def get_user(
    user_id: UUID, _: CurrentModerator, db: Session = Depends(get_db),
):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "user not found")
    memberships = db.query(HouseholdMember).filter_by(user_id=u.id).all()
    listing_count = (
        db.query(Listing)
        .filter(Listing.created_by_user_id == u.id, Listing.deleted_at.is_(None))
        .count()
    )
    return UserDetail(
        **_row(u).model_dump(),
        household_memberships=[
            {"household_id": str(m.household_id), "role": m.role}
            for m in memberships
        ],
        listing_count=listing_count,
    )


@router.patch("/{user_id}")
def patch_user(
    user_id: UUID,
    body: Annotated[dict, Body(...)],
    user: CurrentUser,  # use the base, then branch on body shape + role
    db: Session = Depends(get_db),
):
    """Two body shapes:
      { role: "user"|"moderator"|"admin" }            — admin only
      { is_active: bool, reason: str }                — admin OR moderator
    """
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "user not found")

    if "role" in body:
        if not is_admin(user):
            raise HTTPException(403, "admin required to change role")
        parsed = RolePatch(**body)
        try:
            change_role(db, target=target, new_role=parsed.role, actor=user)
        except HTTPException:
            raise
        db.commit()
        return _row(target)

    if "is_active" in body:
        if not is_at_least_moderator(user):
            raise HTTPException(403, "moderator required")
        parsed = IsActivePatch(**body)
        try:
            set_active(
                db, target=target, is_active=parsed.is_active,
                reason=parsed.reason, actor=user,
            )
        except HTTPException:
            raise
        db.commit()
        return _row(target)

    raise HTTPException(422, "body must include 'role' or 'is_active'")


@router.post("/{user_id}/lock", status_code=status.HTTP_204_NO_CONTENT)
def lock(
    user_id: UUID, body: LockBody,
    actor: CurrentModerator, db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "user not found")
    lock_user(db, target=target, hours=body.hours, reason=body.reason, actor=actor)
    db.commit()


@router.post("/{user_id}/unlock", status_code=status.HTTP_204_NO_CONTENT)
def unlock(
    user_id: UUID, body: ModerationReason,
    actor: CurrentModerator, db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "user not found")
    unlock_user(db, target=target, reason=body.reason, actor=actor)
    db.commit()
```

- [ ] **Step 6: Mount in main.py**

Extend imports and mount under `/api/v1/admin/users`:

```python
from app.routers import (
    admin_flags, admin_settings, admin_users, ai, auth, community, content,
    food, health, me_settings, runtime_config, tracking,
)
...
app.include_router(admin_users.router, prefix="/api/v1/admin/users", tags=["admin"])
```

- [ ] **Step 7: Run tests**

```bash
uv run pytest tests/test_user_management_endpoints.py -q
```

Expected: `12 passed`.

- [ ] **Step 8: Commit**

```bash
git add apps/backend/app/schemas/admin.py \
        apps/backend/app/services/admin/users.py \
        apps/backend/app/routers/admin_users.py \
        apps/backend/app/main.py \
        apps/backend/tests/test_user_management_endpoints.py
git commit -m "feat(admin): /admin/users endpoints (list/detail/role/active/lock/unlock)"
```

---

### Task 14: Community & listing moderation endpoints

**Files:**
- Create: `apps/backend/app/services/admin/moderation.py`
- Create: `apps/backend/app/routers/admin_moderation.py`
- Modify: `apps/backend/app/main.py` (mount)
- Create: `apps/backend/tests/test_moderation_endpoints.py`

- [ ] **Step 1: Write service helpers**

`apps/backend/app/services/admin/moderation.py`:

```python
"""Service helpers for moderating communities and listings."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session as DbSession

from app.models.community import Community, Listing
from app.models.core import AuditLog, Event, User


def take_down_community(db: DbSession, *, community: Community, reason: str, actor: User) -> None:
    if community.deleted_at is None:
        community.deleted_at = datetime.now(timezone.utc)
    db.add(AuditLog(
        actor_user_id=actor.id, action="admin.community.taken_down",
        target_type="community", target_id=community.id,
        payload={"reason": reason},
    ))
    db.add(Event(
        user_id=actor.id, event_type="admin.community.taken_down",
        entity_type="community", entity_id=community.id,
        payload={"reason": reason},
    ))


def restore_community(db: DbSession, *, community: Community, reason: str, actor: User) -> None:
    community.deleted_at = None
    db.add(AuditLog(
        actor_user_id=actor.id, action="admin.community.restored",
        target_type="community", target_id=community.id,
        payload={"reason": reason},
    ))
    db.add(Event(
        user_id=actor.id, event_type="admin.community.restored",
        entity_type="community", entity_id=community.id,
        payload={"reason": reason},
    ))


def take_down_listing(db: DbSession, *, listing: Listing, reason: str, actor: User) -> None:
    if listing.deleted_at is None:
        listing.deleted_at = datetime.now(timezone.utc)
    listing.availability_status = "removed"
    db.add(AuditLog(
        actor_user_id=actor.id, action="admin.listing.taken_down",
        target_type="listing", target_id=listing.id,
        payload={"reason": reason},
    ))
    db.add(Event(
        household_id=listing.household_id, user_id=actor.id,
        event_type="admin.listing.taken_down",
        entity_type="listing", entity_id=listing.id,
        payload={"reason": reason},
    ))


def restore_listing(db: DbSession, *, listing: Listing, reason: str, actor: User) -> None:
    listing.deleted_at = None
    listing.availability_status = "available"
    db.add(AuditLog(
        actor_user_id=actor.id, action="admin.listing.restored",
        target_type="listing", target_id=listing.id,
        payload={"reason": reason},
    ))
    db.add(Event(
        household_id=listing.household_id, user_id=actor.id,
        event_type="admin.listing.restored",
        entity_type="listing", entity_id=listing.id,
        payload={"reason": reason},
    ))
```

- [ ] **Step 2: Write failing tests**

```python
# apps/backend/tests/test_moderation_endpoints.py
import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.main import app
from app.models.community import Community, CommunityItem, Listing

client = TestClient(app)


def _make_community(db, *, name="Test Community", deleted=False):
    c = Community(
        name=name, slug=f"slug-{uuid.uuid4().hex[:6]}",
        created_by_user_id=DEV_USER_ID,
    )
    if deleted:
        from datetime import datetime, timezone
        c.deleted_at = datetime.now(timezone.utc)
    db.add(c)
    db.commit()
    return c


def _make_listing(db, *, household_id=DEV_HOUSEHOLD_ID):
    item = CommunityItem(
        household_id=household_id, name="Drill", category="tool",
        quantity=1, created_by_user_id=DEV_USER_ID,
    )
    db.add(item)
    db.flush()
    listing = Listing(
        item_id=item.id, household_id=household_id,
        created_by_user_id=DEV_USER_ID,
        title="Cordless Drill", availability_status="available",
        allowed_exchange_types=["borrow"], quantity_available=1,
    )
    db.add(listing)
    db.commit()
    return listing


def test_list_communities_moderator(as_moderator, db):
    _make_community(db, name="Alpha")
    r = client.get("/api/v1/admin/communities")
    assert r.status_code == 200
    assert any(row["name"] == "Alpha" for row in r.json())


def test_list_listings_moderator(as_moderator, db):
    _make_listing(db)
    r = client.get("/api/v1/admin/listings")
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_take_down_listing(as_moderator, db):
    listing = _make_listing(db)
    r = client.post(
        f"/api/v1/admin/listings/{listing.id}/take-down",
        json={"reason": "off-platform contact info"},
    )
    assert r.status_code == 204
    db.refresh(listing)
    assert listing.deleted_at is not None
    assert listing.availability_status == "removed"


def test_restore_listing(as_moderator, db):
    listing = _make_listing(db)
    from datetime import datetime, timezone
    listing.deleted_at = datetime.now(timezone.utc)
    listing.availability_status = "removed"
    db.commit()
    r = client.post(
        f"/api/v1/admin/listings/{listing.id}/restore",
        json={"reason": "appeal granted"},
    )
    assert r.status_code == 204
    db.refresh(listing)
    assert listing.deleted_at is None
    assert listing.availability_status == "available"


def test_take_down_requires_reason(as_moderator, db):
    listing = _make_listing(db)
    r = client.post(f"/api/v1/admin/listings/{listing.id}/take-down", json={})
    assert r.status_code == 422


def test_take_down_community(as_moderator, db):
    c = _make_community(db, name="ToTakeDown")
    r = client.post(
        f"/api/v1/admin/communities/{c.id}/take-down",
        json={"reason": "abuse reports"},
    )
    assert r.status_code == 204
    db.refresh(c)
    assert c.deleted_at is not None


def test_audit_log_recorded_with_reason(as_moderator, db):
    from app.models.core import AuditLog
    listing = _make_listing(db)
    client.post(
        f"/api/v1/admin/listings/{listing.id}/take-down",
        json={"reason": "X"},
    )
    rows = db.query(AuditLog).filter_by(action="admin.listing.taken_down").all()
    assert any(r.payload.get("reason") == "X" for r in rows)


def test_regular_user_cannot_moderate(db):
    listing = _make_listing(db)
    r = client.post(
        f"/api/v1/admin/listings/{listing.id}/take-down",
        json={"reason": "x"},
    )
    assert r.status_code == 403


def test_get_community_detail(as_moderator, db):
    c = _make_community(db, name="WithDetail")
    r = client.get(f"/api/v1/admin/communities/{c.id}")
    assert r.status_code == 200
    assert r.json()["name"] == "WithDetail"


def test_get_listing_detail(as_moderator, db):
    listing = _make_listing(db)
    r = client.get(f"/api/v1/admin/listings/{listing.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Cordless Drill"
```

- [ ] **Step 3: Run to confirm failure**

```bash
uv run pytest tests/test_moderation_endpoints.py -q
```

Expected: 404 on every endpoint.

- [ ] **Step 4: Create the router**

`apps/backend/app/routers/admin_moderation.py`:

```python
"""/api/v1/admin/{communities,listings} — moderator-grade moderation surface."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import CurrentModerator
from app.db import get_db
from app.models.community import Community, CommunityMember, Listing, ListingCommunity
from app.schemas.admin import ModerationReason
from app.services.admin.moderation import (
    restore_community, restore_listing, take_down_community, take_down_listing,
)

router = APIRouter()


# --- Communities ---

@router.get("/communities")
def list_communities(
    _: CurrentModerator,
    db: Session = Depends(get_db),
    q: str | None = Query(None),
    include_deleted: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    query = db.query(Community)
    if not include_deleted:
        query = query.filter(Community.deleted_at.is_(None))
    if q:
        query = query.filter(Community.name.ilike(f"%{q}%"))
    rows = query.order_by(Community.created_at.desc()).offset(offset).limit(limit).all()
    return [
        {
            "id": str(c.id), "name": c.name, "slug": c.slug,
            "created_at": c.created_at.isoformat(),
            "deleted_at": c.deleted_at.isoformat() if c.deleted_at else None,
            "created_by_user_id": str(c.created_by_user_id),
        }
        for c in rows
    ]


@router.get("/communities/{cid}")
def get_community(cid: UUID, _: CurrentModerator, db: Session = Depends(get_db)):
    c = db.get(Community, cid)
    if c is None:
        raise HTTPException(404, "community not found")
    member_count = db.query(CommunityMember).filter_by(community_id=cid).count()
    listing_count = (
        db.query(ListingCommunity).filter_by(community_id=cid).count()
    )
    return {
        "id": str(c.id), "name": c.name, "slug": c.slug,
        "created_at": c.created_at.isoformat(),
        "deleted_at": c.deleted_at.isoformat() if c.deleted_at else None,
        "created_by_user_id": str(c.created_by_user_id),
        "member_count": member_count,
        "listing_count": listing_count,
    }


@router.post("/communities/{cid}/take-down", status_code=status.HTTP_204_NO_CONTENT)
def take_down_community_endpoint(
    cid: UUID, body: ModerationReason,
    actor: CurrentModerator, db: Session = Depends(get_db),
):
    c = db.get(Community, cid)
    if c is None:
        raise HTTPException(404, "community not found")
    take_down_community(db, community=c, reason=body.reason, actor=actor)
    db.commit()


@router.post("/communities/{cid}/restore", status_code=status.HTTP_204_NO_CONTENT)
def restore_community_endpoint(
    cid: UUID, body: ModerationReason,
    actor: CurrentModerator, db: Session = Depends(get_db),
):
    c = db.get(Community, cid)
    if c is None:
        raise HTTPException(404, "community not found")
    restore_community(db, community=c, reason=body.reason, actor=actor)
    db.commit()


# --- Listings ---

@router.get("/listings")
def list_listings(
    _: CurrentModerator,
    db: Session = Depends(get_db),
    q: str | None = Query(None),
    availability_status: str | None = Query(None),
    include_deleted: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    query = db.query(Listing)
    if not include_deleted:
        query = query.filter(Listing.deleted_at.is_(None))
    if q:
        query = query.filter(Listing.title.ilike(f"%{q}%"))
    if availability_status:
        query = query.filter(Listing.availability_status == availability_status)
    rows = query.order_by(Listing.created_at.desc()).offset(offset).limit(limit).all()
    return [
        {
            "id": str(l.id), "title": l.title,
            "household_id": str(l.household_id),
            "availability_status": l.availability_status,
            "created_at": l.created_at.isoformat(),
            "deleted_at": l.deleted_at.isoformat() if l.deleted_at else None,
        }
        for l in rows
    ]


@router.get("/listings/{lid}")
def get_listing(lid: UUID, _: CurrentModerator, db: Session = Depends(get_db)):
    l = db.get(Listing, lid)
    if l is None:
        raise HTTPException(404, "listing not found")
    communities = [
        str(lc.community_id)
        for lc in db.query(ListingCommunity).filter_by(listing_id=lid).all()
    ]
    return {
        "id": str(l.id), "title": l.title, "description": l.description,
        "item_id": str(l.item_id), "household_id": str(l.household_id),
        "availability_status": l.availability_status,
        "allowed_exchange_types": l.allowed_exchange_types,
        "quantity_available": l.quantity_available,
        "created_at": l.created_at.isoformat(),
        "deleted_at": l.deleted_at.isoformat() if l.deleted_at else None,
        "shared_with_communities": communities,
    }


@router.post("/listings/{lid}/take-down", status_code=status.HTTP_204_NO_CONTENT)
def take_down_listing_endpoint(
    lid: UUID, body: ModerationReason,
    actor: CurrentModerator, db: Session = Depends(get_db),
):
    l = db.get(Listing, lid)
    if l is None:
        raise HTTPException(404, "listing not found")
    take_down_listing(db, listing=l, reason=body.reason, actor=actor)
    db.commit()


@router.post("/listings/{lid}/restore", status_code=status.HTTP_204_NO_CONTENT)
def restore_listing_endpoint(
    lid: UUID, body: ModerationReason,
    actor: CurrentModerator, db: Session = Depends(get_db),
):
    l = db.get(Listing, lid)
    if l is None:
        raise HTTPException(404, "listing not found")
    restore_listing(db, listing=l, reason=body.reason, actor=actor)
    db.commit()
```

- [ ] **Step 5: Mount it**

In `apps/backend/app/main.py`:

```python
from app.routers import (
    admin_flags, admin_moderation, admin_settings, admin_users,
    ai, auth, community, content, food, health,
    me_settings, runtime_config, tracking,
)
...
app.include_router(admin_moderation.router, prefix="/api/v1/admin", tags=["admin"])
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/test_moderation_endpoints.py -q
```

Expected: `10 passed`.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/app/services/admin/moderation.py \
        apps/backend/app/routers/admin_moderation.py \
        apps/backend/app/main.py \
        apps/backend/tests/test_moderation_endpoints.py
git commit -m "feat(admin): community + listing moderation endpoints"
```

---

### Task 15: Audit log read endpoint

**Files:**
- Create: `apps/backend/app/routers/admin_audit.py`
- Modify: `apps/backend/app/main.py` (mount)
- Create: `apps/backend/tests/test_audit_log_endpoint.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/test_audit_log_endpoint.py
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.auth import DEV_USER_ID
from app.main import app
from app.models.core import AuditLog

client = TestClient(app)


def _seed_audit(db, *, action, days_ago=0):
    db.add(AuditLog(
        actor_user_id=DEV_USER_ID,
        action=action, target_type="x", target_id=None, payload={},
        created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
    ))
    db.commit()


def test_admin_can_read(as_admin, db):
    _seed_audit(db, action="admin.test.write")
    r = client.get("/api/v1/admin/audit-log")
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_moderator_can_read(as_moderator, db):
    _seed_audit(db, action="admin.test.mod_read")
    r = client.get("/api/v1/admin/audit-log")
    assert r.status_code == 200


def test_regular_user_403():
    r = client.get("/api/v1/admin/audit-log")
    assert r.status_code == 403


def test_filter_by_action(as_admin, db):
    _seed_audit(db, action="admin.user.locked")
    _seed_audit(db, action="admin.flag.updated")
    r = client.get("/api/v1/admin/audit-log?action=admin.user.locked")
    assert all(row["action"] == "admin.user.locked" for row in r.json())


def test_filter_by_action_prefix(as_admin, db):
    _seed_audit(db, action="admin.user.locked")
    _seed_audit(db, action="admin.user.unlocked")
    _seed_audit(db, action="admin.flag.updated")
    r = client.get("/api/v1/admin/audit-log?action_prefix=admin.user")
    actions = {row["action"] for row in r.json()}
    assert "admin.flag.updated" not in actions
    assert {"admin.user.locked", "admin.user.unlocked"} <= actions


def test_pagination(as_admin, db):
    for i in range(5):
        _seed_audit(db, action=f"admin.test.p{i}")
    r = client.get("/api/v1/admin/audit-log?limit=2&offset=0")
    assert len(r.json()) == 2
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/test_audit_log_endpoint.py -q
```

Expected: 404.

- [ ] **Step 3: Create the router**

`apps/backend/app/routers/admin_audit.py`:

```python
"""Read-only audit log access for admins and moderators."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import CurrentModerator
from app.db import get_db
from app.models.core import AuditLog

router = APIRouter()


@router.get("/audit-log")
def list_audit_log(
    _: CurrentModerator,
    db: Session = Depends(get_db),
    actor_user_id: UUID | None = Query(None),
    action: str | None = Query(None),
    action_prefix: str | None = Query(None),
    target_type: str | None = Query(None),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    q = db.query(AuditLog)
    if actor_user_id is not None:
        q = q.filter(AuditLog.actor_user_id == actor_user_id)
    if action is not None:
        q = q.filter(AuditLog.action == action)
    if action_prefix is not None:
        q = q.filter(AuditLog.action.startswith(action_prefix))
    if target_type is not None:
        q = q.filter(AuditLog.target_type == target_type)
    if since is not None:
        q = q.filter(AuditLog.created_at >= since)
    if until is not None:
        q = q.filter(AuditLog.created_at < until)
    rows = q.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()
    return [
        {
            "id": str(r.id),
            "actor_user_id": str(r.actor_user_id) if r.actor_user_id else None,
            "action": r.action,
            "target_type": r.target_type,
            "target_id": str(r.target_id) if r.target_id else None,
            "payload": r.payload,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
```

- [ ] **Step 4: Mount it**

In `apps/backend/app/main.py`:

```python
from app.routers import (
    admin_audit, admin_flags, admin_moderation, admin_settings, admin_users,
    ai, auth, community, content, food, health,
    me_settings, runtime_config, tracking,
)
...
app.include_router(admin_audit.router, prefix="/api/v1/admin", tags=["admin"])
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_audit_log_endpoint.py -q
```

Expected: `6 passed`.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/routers/admin_audit.py \
        apps/backend/app/main.py \
        apps/backend/tests/test_audit_log_endpoint.py
git commit -m "feat(admin): /admin/audit-log read endpoint with filters"
```

---

### Task 16: GET /auth/me returns role

**Files:**
- Modify: `apps/backend/app/routers/auth.py` (extend MeResponse)
- Modify: `apps/backend/app/schemas/auth.py` if MeResponse is there
- Modify or add to: `apps/backend/tests/test_auth.py`

- [ ] **Step 1: Find MeResponse**

```bash
grep -nR 'class MeResponse' apps/backend/app/
```

Open the file that owns it. It's likely `apps/backend/app/schemas/auth.py`; the response is built in `apps/backend/app/routers/auth.py:206-229`.

- [ ] **Step 2: Add `role` to the schema**

In the file that defines `MeResponse`, add the field:

```python
role: str  # "user" | "moderator" | "admin"
```

- [ ] **Step 3: Set `role` in the route handler**

In `apps/backend/app/routers/auth.py:me()`, add `role=user.role` to the response construction.

- [ ] **Step 4: Add a test asserting `role` is present**

Append to `apps/backend/tests/test_auth.py` (or a new file `test_auth_me_role.py`):

```python
def test_me_returns_role(as_admin):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    r = c.get("/api/v1/auth/me")
    assert r.status_code == 200
    assert r.json()["role"] == "admin"
```

- [ ] **Step 5: Run**

```bash
uv run pytest tests/test_auth.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/routers/auth.py apps/backend/app/schemas/*.py \
        apps/backend/tests/test_auth*.py
git commit -m "feat(admin): /auth/me response includes role"
```

---

### Task 17: Cross-cutting require_admin / require_moderator regression tests

**Files:**
- Create: `apps/backend/tests/test_require_admin_endpoints.py`
- Create: `apps/backend/tests/test_require_moderator_endpoints.py`

- [ ] **Step 1: Write `test_require_admin_endpoints.py`**

```python
"""Sweeps every admin-only endpoint: 401 unauthenticated, 403 user, 403 moderator, 200 admin."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

ADMIN_ONLY_GET_ENDPOINTS = [
    "/api/v1/admin/settings",
    "/api/v1/admin/settings/registry",
    "/api/v1/admin/flags",
]


@pytest.mark.parametrize("path", ADMIN_ONLY_GET_ENDPOINTS)
def test_unauthenticated_returns_401(path):
    from app.auth import get_current_user
    app.dependency_overrides.pop(get_current_user, None)
    r = client.get(path)
    assert r.status_code == 401, f"{path} returned {r.status_code}"


@pytest.mark.parametrize("path", ADMIN_ONLY_GET_ENDPOINTS)
def test_regular_user_returns_403(path):
    r = client.get(path)
    assert r.status_code == 403, f"{path} returned {r.status_code}"


@pytest.mark.parametrize("path", ADMIN_ONLY_GET_ENDPOINTS)
def test_moderator_returns_403(as_moderator, path):
    r = client.get(path)
    assert r.status_code == 403, f"{path} returned {r.status_code}"


@pytest.mark.parametrize("path", ADMIN_ONLY_GET_ENDPOINTS)
def test_admin_returns_200(as_admin, path):
    r = client.get(path)
    assert r.status_code == 200, f"{path} returned {r.status_code}"
```

- [ ] **Step 2: Write `test_require_moderator_endpoints.py`**

```python
"""Sweeps every moderator-allowed endpoint."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

MOD_OK_GET_ENDPOINTS = [
    "/api/v1/admin/users",
    "/api/v1/admin/communities",
    "/api/v1/admin/listings",
    "/api/v1/admin/audit-log",
]


@pytest.mark.parametrize("path", MOD_OK_GET_ENDPOINTS)
def test_regular_user_403(path):
    r = client.get(path)
    assert r.status_code == 403


@pytest.mark.parametrize("path", MOD_OK_GET_ENDPOINTS)
def test_moderator_200(as_moderator, path):
    r = client.get(path)
    assert r.status_code == 200


@pytest.mark.parametrize("path", MOD_OK_GET_ENDPOINTS)
def test_admin_200(as_admin, path):
    r = client.get(path)
    assert r.status_code == 200
```

- [ ] **Step 3: Run**

```bash
uv run pytest tests/test_require_admin_endpoints.py tests/test_require_moderator_endpoints.py -q
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/tests/test_require_admin_endpoints.py \
        apps/backend/tests/test_require_moderator_endpoints.py
git commit -m "test(admin): cross-cutting role-gate regression tests"
```

---

## Phase 5 — Frontend foundation

### Task 18: Frontend types + API client

**Files:**
- Modify: `apps/web/src/lib/types.ts` (append admin types)
- Modify: `apps/web/src/lib/api.ts` (append admin functions)

- [ ] **Step 1: Append types**

Add to `apps/web/src/lib/types.ts`:

```typescript
// --- Admin / settings / flags / moderation ---

export type Role = "user" | "moderator" | "admin";

export interface RegistryEntry {
  key: string;
  type: "bool" | "int" | "str" | "float";
  default: unknown;
  scopes: ("global" | "household" | "user")[];
  description: string;
  public: boolean;
}

export interface GlobalSettingRow {
  key: string;
  spec: RegistryEntry;
  current_global: unknown;
  has_global_override: boolean;
  household_override_count: number;
  user_override_count: number;
}

export interface SettingDetail {
  key: string;
  spec: RegistryEntry;
  current_global: unknown;
  has_global_override: boolean;
  household_overrides: { household_id: string; value: unknown; updated_at: string }[];
  user_overrides: { user_id: string; value: unknown; updated_at: string }[];
}

export interface FeatureFlag {
  key: string;
  description: string | null;
  enabled_globally: boolean;
  rollout_percent: number;
  household_override_count: number;
  user_override_count: number;
}

export interface FeatureFlagDetail extends FeatureFlag {
  household_overrides: { id: string; household_id: string; enabled: boolean }[];
  user_overrides: { id: string; user_id: string; enabled: boolean }[];
}

export interface AdminUserRow {
  id: string;
  email: string;
  display_name: string | null;
  role: Role;
  is_active: boolean;
  locked_until: string | null;
  created_at: string;
}

export interface AdminUserDetail extends AdminUserRow {
  household_memberships: { household_id: string; role: string }[];
  listing_count: number;
}

export interface AdminCommunityRow {
  id: string;
  name: string;
  slug: string;
  created_at: string;
  deleted_at: string | null;
  created_by_user_id: string;
}

export interface AdminCommunityDetail extends AdminCommunityRow {
  member_count: number;
  listing_count: number;
}

export interface AdminListingRow {
  id: string;
  title: string;
  household_id: string;
  availability_status: string;
  created_at: string;
  deleted_at: string | null;
}

export interface AdminListingDetail extends AdminListingRow {
  description: string | null;
  item_id: string;
  allowed_exchange_types: string[];
  quantity_available: number;
  shared_with_communities: string[];
}

export interface AuditLogEntry {
  id: string;
  actor_user_id: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface RuntimeConfig {
  signups_open?: boolean;
  maintenance_message?: string;
}
```

- [ ] **Step 2: Append API functions**

Add to `apps/web/src/lib/api.ts`:

```typescript
import type {
  AdminCommunityDetail, AdminCommunityRow, AdminListingDetail, AdminListingRow,
  AdminUserDetail, AdminUserRow, AuditLogEntry, FeatureFlag, FeatureFlagDetail,
  GlobalSettingRow, RegistryEntry, RuntimeConfig, SettingDetail,
} from "./types";

// --- Runtime config (public, no auth) ---
export const getRuntimeConfig = () => api<RuntimeConfig>("/runtime-config");

// --- Admin: settings ---
export const listAdminSettings = () => api<GlobalSettingRow[]>("/admin/settings");
export const getAdminSettingsRegistry = () =>
  api<Record<string, RegistryEntry>>("/admin/settings/registry");
export const getAdminSetting = (key: string) =>
  api<SettingDetail>(`/admin/settings/${encodeURIComponent(key)}`);
export const setAdminSettingGlobal = (key: string, value: unknown) =>
  api(`/admin/settings/${encodeURIComponent(key)}`, {
    method: "PUT", body: JSON.stringify({ value }),
  });
export const clearAdminSettingGlobal = (key: string) =>
  api(`/admin/settings/${encodeURIComponent(key)}`, { method: "DELETE" });
export const setAdminSettingHousehold = (key: string, hid: string, value: unknown) =>
  api(`/admin/settings/${encodeURIComponent(key)}/household/${hid}`, {
    method: "PUT", body: JSON.stringify({ value }),
  });
export const clearAdminSettingHousehold = (key: string, hid: string) =>
  api(`/admin/settings/${encodeURIComponent(key)}/household/${hid}`, { method: "DELETE" });
export const setAdminSettingUser = (key: string, uid: string, value: unknown) =>
  api(`/admin/settings/${encodeURIComponent(key)}/user/${uid}`, {
    method: "PUT", body: JSON.stringify({ value }),
  });
export const clearAdminSettingUser = (key: string, uid: string) =>
  api(`/admin/settings/${encodeURIComponent(key)}/user/${uid}`, { method: "DELETE" });

// --- Admin: flags ---
export const listAdminFlags = () => api<FeatureFlag[]>("/admin/flags");
export const getAdminFlag = (key: string) =>
  api<FeatureFlagDetail>(`/admin/flags/${encodeURIComponent(key)}`);
export const createAdminFlag = (body: {
  key: string; description?: string; enabled_globally?: boolean; rollout_percent?: number;
}) => api<FeatureFlag>("/admin/flags", { method: "POST", body: JSON.stringify(body) });
export const patchAdminFlag = (key: string, body: {
  description?: string; enabled_globally?: boolean; rollout_percent?: number;
}) => api<FeatureFlag>(`/admin/flags/${encodeURIComponent(key)}`, {
  method: "PATCH", body: JSON.stringify(body),
});
export const deleteAdminFlag = (key: string) =>
  api(`/admin/flags/${encodeURIComponent(key)}`, { method: "DELETE" });
export const setAdminFlagHouseholdOverride = (key: string, hid: string, enabled: boolean) =>
  api(`/admin/flags/${encodeURIComponent(key)}/household/${hid}`, {
    method: "PUT", body: JSON.stringify({ enabled }),
  });
export const setAdminFlagUserOverride = (key: string, uid: string, enabled: boolean) =>
  api(`/admin/flags/${encodeURIComponent(key)}/user/${uid}`, {
    method: "PUT", body: JSON.stringify({ enabled }),
  });

// --- Admin: users ---
export const listAdminUsers = (params: { q?: string; role?: string; active?: boolean } = {}) => {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.role) qs.set("role", params.role);
  if (params.active !== undefined) qs.set("active", String(params.active));
  return api<AdminUserRow[]>(`/admin/users${qs.toString() ? `?${qs}` : ""}`);
};
export const getAdminUser = (id: string) =>
  api<AdminUserDetail>(`/admin/users/${id}`);
export const patchAdminUserRole = (id: string, role: string) =>
  api<AdminUserRow>(`/admin/users/${id}`, {
    method: "PATCH", body: JSON.stringify({ role }),
  });
export const patchAdminUserActive = (id: string, is_active: boolean, reason: string) =>
  api<AdminUserRow>(`/admin/users/${id}`, {
    method: "PATCH", body: JSON.stringify({ is_active, reason }),
  });
export const lockAdminUser = (id: string, hours: number, reason: string) =>
  api(`/admin/users/${id}/lock`, {
    method: "POST", body: JSON.stringify({ hours, reason }),
  });
export const unlockAdminUser = (id: string, reason: string) =>
  api(`/admin/users/${id}/unlock`, {
    method: "POST", body: JSON.stringify({ reason }),
  });

// --- Admin: communities + listings ---
export const listAdminCommunities = (params: { q?: string; include_deleted?: boolean } = {}) => {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.include_deleted) qs.set("include_deleted", "true");
  return api<AdminCommunityRow[]>(`/admin/communities${qs.toString() ? `?${qs}` : ""}`);
};
export const getAdminCommunity = (id: string) =>
  api<AdminCommunityDetail>(`/admin/communities/${id}`);
export const takeDownAdminCommunity = (id: string, reason: string) =>
  api(`/admin/communities/${id}/take-down`, {
    method: "POST", body: JSON.stringify({ reason }),
  });
export const restoreAdminCommunity = (id: string, reason: string) =>
  api(`/admin/communities/${id}/restore`, {
    method: "POST", body: JSON.stringify({ reason }),
  });

export const listAdminListings = (params: { q?: string; availability_status?: string } = {}) => {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.availability_status) qs.set("availability_status", params.availability_status);
  return api<AdminListingRow[]>(`/admin/listings${qs.toString() ? `?${qs}` : ""}`);
};
export const getAdminListing = (id: string) =>
  api<AdminListingDetail>(`/admin/listings/${id}`);
export const takeDownAdminListing = (id: string, reason: string) =>
  api(`/admin/listings/${id}/take-down`, {
    method: "POST", body: JSON.stringify({ reason }),
  });
export const restoreAdminListing = (id: string, reason: string) =>
  api(`/admin/listings/${id}/restore`, {
    method: "POST", body: JSON.stringify({ reason }),
  });

// --- Admin: audit log ---
export const listAdminAuditLog = (params: {
  actor_user_id?: string; action?: string; action_prefix?: string;
  target_type?: string; limit?: number; offset?: number;
} = {}) => {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined) qs.set(k, String(v));
  });
  return api<AuditLogEntry[]>(`/admin/audit-log${qs.toString() ? `?${qs}` : ""}`);
};
```

- [ ] **Step 2: Typecheck**

```bash
cd apps/web
pnpm typecheck
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/lib/types.ts apps/web/src/lib/api.ts
git commit -m "feat(admin/web): types and API client for admin endpoints"
```

---

### Task 19: RoleBadge + Sidebar admin section

**Files:**
- Create: `apps/web/src/components/RoleBadge.tsx`
- Modify: `apps/web/src/components/Sidebar.tsx` (conditional Admin section + role badge)

- [ ] **Step 1: Create the `RoleBadge` component**

`apps/web/src/components/RoleBadge.tsx`:

```tsx
import type { Role } from "@/lib/types";

const STYLES: Record<Role, string> = {
  admin: "bg-amber-200 text-amber-900",
  moderator: "bg-stone-200 text-stone-800",
  user: "bg-transparent text-stone-500",
};

const LABELS: Record<Role, string> = {
  admin: "ADMIN",
  moderator: "MOD",
  user: "",
};

export function RoleBadge({ role }: { role: Role }) {
  if (role === "user") return null;
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wider ${STYLES[role]}`}
    >
      {LABELS[role]}
    </span>
  );
}
```

- [ ] **Step 2: Wire into Sidebar**

Open `apps/web/src/components/Sidebar.tsx`. The exact integration depends on the existing structure; the changes are:

1. Read the current user's role (likely via the auth context or a `useMe()` hook; if neither exists, fetch `/auth/me` on mount and store in component state).
2. After the existing community section, conditionally render:

```tsx
import { RoleBadge } from "./RoleBadge";

// inside the component, after the existing nav sections:
{role === "admin" || role === "moderator" ? (
  <section className="mt-6">
    <h3 className="px-3 text-xs font-semibold uppercase tracking-wider text-stone-500">
      Admin <RoleBadge role={role} />
    </h3>
    <ul className="mt-2 space-y-1">
      <SidebarLink href="/admin">Home</SidebarLink>
      <SidebarLink href="/admin/users">Users</SidebarLink>
      <SidebarLink href="/admin/communities">Communities</SidebarLink>
      <SidebarLink href="/admin/listings">Listings</SidebarLink>
      <SidebarLink href="/admin/audit-log">Audit log</SidebarLink>
      {role === "admin" && (
        <>
          <SidebarLink href="/admin/settings">Settings</SidebarLink>
          <SidebarLink href="/admin/flags">Flags</SidebarLink>
          <SidebarLink href="/admin/banner">Banner</SidebarLink>
        </>
      )}
    </ul>
  </section>
) : null}
```

`SidebarLink` is whatever the file already uses for nav items (reuse it, don't invent a new pattern).

- [ ] **Step 3: Typecheck + visual smoke**

```bash
pnpm typecheck
pnpm dev
```

Visit `http://localhost:3000` — the Admin section should appear only if you're logged in as the bootstrap admin (or a promoted moderator).

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/RoleBadge.tsx apps/web/src/components/Sidebar.tsx
git commit -m "feat(admin/web): RoleBadge + Admin sidebar section gated by role"
```

---

### Task 20: MaintenanceBanner + public runtime-config

**Files:**
- Create: `apps/web/src/components/MaintenanceBanner.tsx`
- Modify: `apps/web/src/app/layout.tsx`

- [ ] **Step 1: Create the banner component**

`apps/web/src/components/MaintenanceBanner.tsx`:

```tsx
"use client";
import { useEffect, useState } from "react";
import { getRuntimeConfig } from "@/lib/api";

export function MaintenanceBanner() {
  const [message, setMessage] = useState<string>("");

  useEffect(() => {
    getRuntimeConfig()
      .then((cfg) => setMessage(cfg.maintenance_message ?? ""))
      .catch(() => {/* silent — no banner on fetch failure */});
  }, []);

  if (!message) return null;

  return (
    <div className="w-full border-b border-amber-200 bg-amber-50 px-4 py-2 text-center text-sm text-amber-900">
      {message}
    </div>
  );
}
```

- [ ] **Step 2: Mount it in root layout**

In `apps/web/src/app/layout.tsx`, inside the `<body>` tag, above whatever wraps the existing chrome:

```tsx
import { MaintenanceBanner } from "@/components/MaintenanceBanner";

// ...
<body>
  <MaintenanceBanner />
  {/* existing layout chrome */}
</body>
```

- [ ] **Step 3: Smoke check**

```bash
pnpm dev
```

In one terminal, with admin logged in:
```bash
curl -X PUT http://localhost:8000/api/v1/admin/settings/maintenance_message \
  -H "Cookie: hearth_session=…" \
  -H "Content-Type: application/json" \
  -d '{"value":"Scheduled maintenance Sun 2am"}'
```

Refresh the browser — banner should appear.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/MaintenanceBanner.tsx apps/web/src/app/layout.tsx
git commit -m "feat(admin/web): MaintenanceBanner driven by public /runtime-config"
```

---

### Task 21: /admin layout + home page

**Files:**
- Create: `apps/web/src/app/admin/layout.tsx`
- Create: `apps/web/src/app/admin/page.tsx`

- [ ] **Step 1: Create the layout (server-side checks via API; client gate is UX)**

`apps/web/src/app/admin/layout.tsx`:

```tsx
"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Role } from "@/lib/types";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [role, setRole] = useState<Role | null>(null);

  useEffect(() => {
    api<{ role: Role }>("/auth/me")
      .then((me) => {
        if (me.role !== "admin" && me.role !== "moderator") {
          router.replace("/");
        } else {
          setRole(me.role);
        }
      })
      .catch(() => router.replace("/login"));
  }, [router]);

  if (role === null) {
    return <div className="p-8 text-stone-500">Loading…</div>;
  }

  return <div className="min-h-screen">{children}</div>;
}
```

- [ ] **Step 2: Create the admin home page**

`apps/web/src/app/admin/page.tsx`:

```tsx
"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, listAdminAuditLog } from "@/lib/api";
import type { AuditLogEntry, Role } from "@/lib/types";

interface Tile {
  href: string;
  title: string;
  description: string;
  adminOnly?: boolean;
}

const TILES: Tile[] = [
  { href: "/admin/users",       title: "Users",       description: "Search, lock, promote." },
  { href: "/admin/communities", title: "Communities", description: "Review and take down." },
  { href: "/admin/listings",    title: "Listings",    description: "Review and take down." },
  { href: "/admin/audit-log",   title: "Audit log",   description: "Every admin action, ever." },
  { href: "/admin/settings",    title: "Settings",    description: "Global, household, user.", adminOnly: true },
  { href: "/admin/flags",       title: "Flags",       description: "Feature flags + overrides.", adminOnly: true },
  { href: "/admin/banner",      title: "Banner",      description: "Public maintenance message.", adminOnly: true },
];

export default function AdminHome() {
  const [role, setRole] = useState<Role>("user");
  const [recent, setRecent] = useState<AuditLogEntry[]>([]);

  useEffect(() => {
    api<{ role: Role }>("/auth/me").then((me) => setRole(me.role));
    listAdminAuditLog({ limit: 10 }).then(setRecent).catch(() => {/* nbd */});
  }, []);

  const visibleTiles = TILES.filter((t) => !t.adminOnly || role === "admin");

  return (
    <div className="mx-auto max-w-6xl space-y-8 p-8">
      <h1 className="font-serif text-3xl text-stone-900">Admin</h1>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {visibleTiles.map((t) => (
          <Link
            key={t.href}
            href={t.href}
            className="rounded-lg border border-stone-200 bg-white p-5 transition hover:border-amber-300 hover:shadow"
          >
            <div className="font-serif text-lg text-stone-900">{t.title}</div>
            <div className="mt-1 text-sm text-stone-500">{t.description}</div>
          </Link>
        ))}
      </div>

      <section>
        <h2 className="mb-2 font-serif text-xl text-stone-900">Recent activity</h2>
        <ul className="divide-y divide-stone-100 rounded-lg border border-stone-200 bg-white">
          {recent.map((r) => (
            <li key={r.id} className="px-4 py-2 text-sm">
              <span className="font-mono text-xs text-stone-400">
                {new Date(r.created_at).toLocaleString()}
              </span>{" "}
              <span className="text-stone-800">{r.action}</span>
              {r.target_type && (
                <span className="text-stone-400"> · {r.target_type}</span>
              )}
            </li>
          ))}
          {recent.length === 0 && (
            <li className="px-4 py-3 text-sm text-stone-400">No activity yet.</li>
          )}
        </ul>
      </section>
    </div>
  );
}
```

- [ ] **Step 3: Typecheck**

```bash
cd apps/web
pnpm typecheck
```

Expected: no errors.

- [ ] **Step 4: Smoke check**

```bash
pnpm dev
```

Visit `http://localhost:3000/admin` (logged in as admin) — see the tile grid + recent activity. Visit as regular user — redirected to `/`.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/app/admin/layout.tsx apps/web/src/app/admin/page.tsx
git commit -m "feat(admin/web): /admin layout (role gate) + home page"
```

---

## Phase 6 — Admin pages

### Task 22: ReasonModal shared component

**Files:**
- Create: `apps/web/src/components/ReasonModal.tsx`

- [ ] **Step 1: Create the component**

`apps/web/src/components/ReasonModal.tsx`:

```tsx
"use client";
import { useState } from "react";

interface Props {
  open: boolean;
  title: string;
  actionLabel: string;
  destructive?: boolean;
  onCancel: () => void;
  onConfirm: (reason: string) => void | Promise<void>;
}

export function ReasonModal({
  open, title, actionLabel, destructive, onCancel, onConfirm,
}: Props) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  if (!open) return null;

  const trimmed = reason.trim();
  const valid = trimmed.length >= 3;

  const submit = async () => {
    if (!valid || busy) return;
    setBusy(true);
    try {
      await onConfirm(trimmed);
      setReason("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/40 p-4"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="font-serif text-xl text-stone-900">{title}</h2>
        <label className="mt-4 block text-sm font-medium text-stone-700">
          Reason (required, min 3 chars)
        </label>
        <textarea
          autoFocus
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          className="mt-1 w-full rounded border border-stone-300 px-3 py-2 text-sm focus:border-amber-400 focus:outline-none"
          placeholder="Why are you doing this?"
        />
        <div className="mt-5 flex justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            className="rounded px-4 py-2 text-sm text-stone-600 hover:bg-stone-100"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={!valid || busy}
            className={`rounded px-4 py-2 text-sm text-white disabled:cursor-not-allowed disabled:opacity-50 ${
              destructive
                ? "bg-red-600 hover:bg-red-700"
                : "bg-amber-600 hover:bg-amber-700"
            }`}
          >
            {busy ? "…" : actionLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

```bash
cd apps/web && pnpm typecheck
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/ReasonModal.tsx
git commit -m "feat(admin/web): ReasonModal shared component"
```

---

### Task 23: /admin/users page

**Files:**
- Create: `apps/web/src/app/admin/users/page.tsx`

- [ ] **Step 1: Create the page**

`apps/web/src/app/admin/users/page.tsx`:

```tsx
"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { ReasonModal } from "@/components/ReasonModal";
import { RoleBadge } from "@/components/RoleBadge";
import {
  api, listAdminUsers, lockAdminUser,
  patchAdminUserActive, patchAdminUserRole, unlockAdminUser,
} from "@/lib/api";
import type { AdminUserRow, Role } from "@/lib/types";

type ModalState =
  | null
  | { kind: "deactivate"; user: AdminUserRow }
  | { kind: "activate"; user: AdminUserRow }
  | { kind: "lock"; user: AdminUserRow }
  | { kind: "unlock"; user: AdminUserRow };

export default function AdminUsersPage() {
  const [me, setMe] = useState<Role>("user");
  const [users, setUsers] = useState<AdminUserRow[]>([]);
  const [q, setQ] = useState("");
  const [modal, setModal] = useState<ModalState>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = () => listAdminUsers({ q: q || undefined }).then(setUsers);

  useEffect(() => {
    api<{ role: Role }>("/auth/me").then((m) => setMe(m.role));
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const isAdmin = me === "admin";
  const adminCount = useMemo(
    () => users.filter((u) => u.role === "admin" && u.is_active).length,
    [users],
  );

  const onConfirm = async (reason: string) => {
    if (!modal) return;
    setError(null);
    try {
      if (modal.kind === "deactivate") {
        await patchAdminUserActive(modal.user.id, false, reason);
      } else if (modal.kind === "activate") {
        await patchAdminUserActive(modal.user.id, true, reason);
      } else if (modal.kind === "lock") {
        await lockAdminUser(modal.user.id, 24, reason);  // 24h default
      } else if (modal.kind === "unlock") {
        await unlockAdminUser(modal.user.id, reason);
      }
      setModal(null);
      await reload();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Action failed");
    }
  };

  const promote = async (u: AdminUserRow, role: Role) => {
    setError(null);
    try {
      await patchAdminUserRole(u.id, role);
      await reload();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Role change failed");
    }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-8">
      <h1 className="font-serif text-2xl text-stone-900">Users</h1>

      <div className="flex items-center gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") reload(); }}
          placeholder="Search by email"
          className="rounded border border-stone-300 px-3 py-1.5 text-sm"
        />
        <button
          onClick={() => reload()}
          className="rounded bg-amber-600 px-3 py-1.5 text-sm text-white hover:bg-amber-700"
        >
          Search
        </button>
      </div>

      {error && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-stone-200 bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-stone-50 text-left text-xs uppercase tracking-wider text-stone-500">
            <tr>
              <th className="px-4 py-2">Email</th>
              <th className="px-4 py-2">Name</th>
              <th className="px-4 py-2">Role</th>
              <th className="px-4 py-2">Active</th>
              <th className="px-4 py-2">Locked</th>
              <th className="px-4 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100">
            {users.map((u) => {
              const isLastAdmin = u.role === "admin" && u.is_active && adminCount === 1;
              const locked = u.locked_until && new Date(u.locked_until) > new Date();
              return (
                <tr key={u.id} className="hover:bg-stone-50">
                  <td className="px-4 py-2">
                    <Link href={`/admin/users/${u.id}`} className="hover:underline">
                      {u.email}
                    </Link>
                  </td>
                  <td className="px-4 py-2 text-stone-500">{u.display_name ?? "—"}</td>
                  <td className="px-4 py-2"><RoleBadge role={u.role} /> {u.role === "user" && <span className="text-stone-400 text-xs">user</span>}</td>
                  <td className="px-4 py-2">{u.is_active ? "✓" : "—"}</td>
                  <td className="px-4 py-2 text-stone-500">
                    {locked ? new Date(u.locked_until!).toLocaleString() : "—"}
                  </td>
                  <td className="px-4 py-2 text-right space-x-1">
                    {isAdmin && (
                      <select
                        value={u.role}
                        disabled={isLastAdmin}
                        onChange={(e) => promote(u, e.target.value as Role)}
                        className="rounded border border-stone-200 px-1 py-0.5 text-xs disabled:opacity-50"
                        title={isLastAdmin ? "Cannot demote the last active admin" : ""}
                      >
                        <option value="user">user</option>
                        <option value="moderator">moderator</option>
                        <option value="admin">admin</option>
                      </select>
                    )}
                    {u.is_active ? (
                      <button
                        onClick={() => setModal({ kind: "deactivate", user: u })}
                        disabled={isLastAdmin}
                        className="rounded bg-stone-100 px-2 py-1 text-xs hover:bg-stone-200 disabled:opacity-50"
                      >
                        Deactivate
                      </button>
                    ) : (
                      <button
                        onClick={() => setModal({ kind: "activate", user: u })}
                        className="rounded bg-stone-100 px-2 py-1 text-xs hover:bg-stone-200"
                      >
                        Activate
                      </button>
                    )}
                    {locked ? (
                      <button
                        onClick={() => setModal({ kind: "unlock", user: u })}
                        className="rounded bg-stone-100 px-2 py-1 text-xs hover:bg-stone-200"
                      >
                        Unlock
                      </button>
                    ) : (
                      <button
                        onClick={() => setModal({ kind: "lock", user: u })}
                        className="rounded bg-stone-100 px-2 py-1 text-xs hover:bg-stone-200"
                      >
                        Lock 24h
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <ReasonModal
        open={modal !== null}
        title={
          modal?.kind === "deactivate" ? `Deactivate ${modal.user.email}` :
          modal?.kind === "activate"   ? `Activate ${modal.user.email}` :
          modal?.kind === "lock"       ? `Lock ${modal.user.email} for 24h` :
          modal?.kind === "unlock"     ? `Unlock ${modal.user.email}` :
          ""
        }
        actionLabel={
          modal?.kind === "deactivate" ? "Deactivate" :
          modal?.kind === "activate"   ? "Activate" :
          modal?.kind === "lock"       ? "Lock" :
          modal?.kind === "unlock"     ? "Unlock" : "Confirm"
        }
        destructive={modal?.kind === "deactivate" || modal?.kind === "lock"}
        onCancel={() => setModal(null)}
        onConfirm={onConfirm}
      />
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

```bash
pnpm typecheck
```

Expected: no errors.

- [ ] **Step 3: Smoke check**

```bash
pnpm dev
```

Visit `/admin/users` as admin → see role dropdown + all actions. As moderator → no role dropdown; Activate/Deactivate/Lock/Unlock still visible.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/app/admin/users/page.tsx
git commit -m "feat(admin/web): /admin/users list + actions (role/lock/active)"
```

---

### Task 24: /admin/users/[id] detail page

**Files:**
- Create: `apps/web/src/app/admin/users/[id]/page.tsx`

- [ ] **Step 1: Create the page**

`apps/web/src/app/admin/users/[id]/page.tsx`:

```tsx
"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { RoleBadge } from "@/components/RoleBadge";
import { getAdminUser, listAdminAuditLog } from "@/lib/api";
import type { AdminUserDetail, AuditLogEntry } from "@/lib/types";

export default function AdminUserDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [user, setUser] = useState<AdminUserDetail | null>(null);
  const [audit, setAudit] = useState<AuditLogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getAdminUser(id).then(setUser).catch((e) => setError(String(e)));
    // Audit entries that name this user as the target
    listAdminAuditLog({ limit: 50 })
      .then((rows) => setAudit(rows.filter((r) => r.target_id === id)))
      .catch(() => {/* nbd */});
  }, [id]);

  if (error) return <div className="p-8 text-red-700">{error}</div>;
  if (!user) return <div className="p-8 text-stone-500">Loading…</div>;

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-8">
      <Link href="/admin/users" className="text-sm text-stone-500 hover:underline">
        ← Back to users
      </Link>

      <header>
        <h1 className="font-serif text-2xl text-stone-900">
          {user.display_name ?? user.email} <RoleBadge role={user.role} />
        </h1>
        <p className="text-sm text-stone-500">{user.email}</p>
      </header>

      <section className="rounded-lg border border-stone-200 bg-white p-5 text-sm">
        <dl className="grid grid-cols-2 gap-y-2">
          <dt className="text-stone-500">Role</dt><dd>{user.role}</dd>
          <dt className="text-stone-500">Active</dt><dd>{user.is_active ? "Yes" : "No"}</dd>
          <dt className="text-stone-500">Locked until</dt>
          <dd>{user.locked_until ? new Date(user.locked_until).toLocaleString() : "—"}</dd>
          <dt className="text-stone-500">Joined</dt>
          <dd>{new Date(user.created_at).toLocaleString()}</dd>
          <dt className="text-stone-500">Listings owned</dt><dd>{user.listing_count}</dd>
        </dl>
      </section>

      <section>
        <h2 className="mb-2 font-serif text-lg text-stone-900">Households</h2>
        <ul className="space-y-1 text-sm">
          {user.household_memberships.length === 0 && <li className="text-stone-400">None</li>}
          {user.household_memberships.map((m) => (
            <li key={m.household_id}>
              <span className="font-mono text-xs text-stone-400">{m.household_id}</span>
              <span className="ml-2 text-stone-700">{m.role}</span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="mb-2 font-serif text-lg text-stone-900">Recent audit ({audit.length})</h2>
        <ul className="divide-y divide-stone-100 rounded-lg border border-stone-200 bg-white text-sm">
          {audit.length === 0 && <li className="px-4 py-2 text-stone-400">No entries yet.</li>}
          {audit.map((r) => (
            <li key={r.id} className="px-4 py-2">
              <div className="text-xs text-stone-400">
                {new Date(r.created_at).toLocaleString()} ·{" "}
                <span className="font-mono">{r.actor_user_id?.slice(0, 8)}</span>
              </div>
              <div className="text-stone-800">{r.action}</div>
              {r.payload && Object.keys(r.payload).length > 0 && (
                <pre className="mt-1 max-h-32 overflow-auto rounded bg-stone-50 px-2 py-1 text-[11px] text-stone-600">
                  {JSON.stringify(r.payload, null, 2)}
                </pre>
              )}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

```bash
pnpm typecheck
```

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/app/admin/users/[id]/page.tsx
git commit -m "feat(admin/web): /admin/users/[id] detail with audit trail"
```

---

### Task 25: /admin/communities list + detail pages

**Files:**
- Create: `apps/web/src/app/admin/communities/page.tsx`
- Create: `apps/web/src/app/admin/communities/[id]/page.tsx`

- [ ] **Step 1: Create the list page**

`apps/web/src/app/admin/communities/page.tsx`:

```tsx
"use client";
import Link from "next/link";
import { useEffect, useState } from "react";

import { ReasonModal } from "@/components/ReasonModal";
import {
  listAdminCommunities, restoreAdminCommunity, takeDownAdminCommunity,
} from "@/lib/api";
import type { AdminCommunityRow } from "@/lib/types";

export default function AdminCommunitiesPage() {
  const [rows, setRows] = useState<AdminCommunityRow[]>([]);
  const [q, setQ] = useState("");
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [modal, setModal] = useState<
    | null
    | { kind: "take-down"; row: AdminCommunityRow }
    | { kind: "restore"; row: AdminCommunityRow }
  >(null);

  const reload = () =>
    listAdminCommunities({ q: q || undefined, include_deleted: includeDeleted }).then(setRows);

  useEffect(() => { reload(); /* eslint-disable-line */ }, [includeDeleted]);

  const onConfirm = async (reason: string) => {
    if (!modal) return;
    if (modal.kind === "take-down") {
      await takeDownAdminCommunity(modal.row.id, reason);
    } else {
      await restoreAdminCommunity(modal.row.id, reason);
    }
    setModal(null);
    await reload();
  };

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-8">
      <h1 className="font-serif text-2xl text-stone-900">Communities</h1>

      <div className="flex items-center gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") reload(); }}
          placeholder="Search by name"
          className="rounded border border-stone-300 px-3 py-1.5 text-sm"
        />
        <button onClick={() => reload()} className="rounded bg-amber-600 px-3 py-1.5 text-sm text-white">
          Search
        </button>
        <label className="ml-4 text-sm text-stone-600">
          <input
            type="checkbox"
            checked={includeDeleted}
            onChange={(e) => setIncludeDeleted(e.target.checked)}
            className="mr-1"
          />
          Include taken-down
        </label>
      </div>

      <div className="overflow-x-auto rounded-lg border border-stone-200 bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-stone-50 text-left text-xs uppercase tracking-wider text-stone-500">
            <tr>
              <th className="px-4 py-2">Name</th>
              <th className="px-4 py-2">Slug</th>
              <th className="px-4 py-2">Created</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100">
            {rows.map((c) => (
              <tr key={c.id} className="hover:bg-stone-50">
                <td className="px-4 py-2">
                  <Link href={`/admin/communities/${c.id}`} className="hover:underline">
                    {c.name}
                  </Link>
                </td>
                <td className="px-4 py-2 font-mono text-xs text-stone-500">{c.slug}</td>
                <td className="px-4 py-2 text-stone-500">
                  {new Date(c.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-2">
                  {c.deleted_at ? (
                    <span className="rounded bg-red-100 px-2 py-0.5 text-xs text-red-800">
                      Taken down
                    </span>
                  ) : (
                    <span className="text-stone-400 text-xs">live</span>
                  )}
                </td>
                <td className="px-4 py-2 text-right">
                  {c.deleted_at ? (
                    <button
                      onClick={() => setModal({ kind: "restore", row: c })}
                      className="rounded bg-stone-100 px-2 py-1 text-xs hover:bg-stone-200"
                    >
                      Restore
                    </button>
                  ) : (
                    <button
                      onClick={() => setModal({ kind: "take-down", row: c })}
                      className="rounded bg-red-100 px-2 py-1 text-xs text-red-800 hover:bg-red-200"
                    >
                      Take down
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ReasonModal
        open={modal !== null}
        title={
          modal?.kind === "take-down" ? `Take down ${modal.row.name}` :
          modal?.kind === "restore"   ? `Restore ${modal.row.name}` : ""
        }
        actionLabel={modal?.kind === "take-down" ? "Take down" : "Restore"}
        destructive={modal?.kind === "take-down"}
        onCancel={() => setModal(null)}
        onConfirm={onConfirm}
      />
    </div>
  );
}
```

- [ ] **Step 2: Create the detail page**

`apps/web/src/app/admin/communities/[id]/page.tsx`:

```tsx
"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ReasonModal } from "@/components/ReasonModal";
import {
  getAdminCommunity, restoreAdminCommunity, takeDownAdminCommunity,
} from "@/lib/api";
import type { AdminCommunityDetail } from "@/lib/types";

export default function AdminCommunityDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [c, setC] = useState<AdminCommunityDetail | null>(null);
  const [modal, setModal] = useState<null | "take-down" | "restore">(null);
  const reload = () => getAdminCommunity(id).then(setC);

  useEffect(() => { reload(); /* eslint-disable-line */ }, [id]);

  if (!c) return <div className="p-8 text-stone-500">Loading…</div>;

  const onConfirm = async (reason: string) => {
    if (modal === "take-down") await takeDownAdminCommunity(id, reason);
    if (modal === "restore")   await restoreAdminCommunity(id, reason);
    setModal(null);
    await reload();
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-8">
      <Link href="/admin/communities" className="text-sm text-stone-500 hover:underline">
        ← Back to communities
      </Link>
      <header className="flex items-start justify-between">
        <div>
          <h1 className="font-serif text-2xl text-stone-900">{c.name}</h1>
          <p className="text-sm text-stone-500 font-mono">{c.slug}</p>
        </div>
        {c.deleted_at ? (
          <button
            onClick={() => setModal("restore")}
            className="rounded bg-stone-100 px-3 py-1.5 text-sm hover:bg-stone-200"
          >
            Restore
          </button>
        ) : (
          <button
            onClick={() => setModal("take-down")}
            className="rounded bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-700"
          >
            Take down
          </button>
        )}
      </header>

      <section className="rounded-lg border border-stone-200 bg-white p-5 text-sm">
        <dl className="grid grid-cols-2 gap-y-2">
          <dt className="text-stone-500">Status</dt>
          <dd>{c.deleted_at ? `Taken down ${new Date(c.deleted_at).toLocaleString()}` : "Live"}</dd>
          <dt className="text-stone-500">Members</dt><dd>{c.member_count}</dd>
          <dt className="text-stone-500">Listings</dt><dd>{c.listing_count}</dd>
          <dt className="text-stone-500">Created</dt><dd>{new Date(c.created_at).toLocaleString()}</dd>
          <dt className="text-stone-500">Creator</dt>
          <dd className="font-mono text-xs">{c.created_by_user_id}</dd>
        </dl>
      </section>

      <ReasonModal
        open={modal !== null}
        title={modal === "take-down" ? `Take down ${c.name}` : `Restore ${c.name}`}
        actionLabel={modal === "take-down" ? "Take down" : "Restore"}
        destructive={modal === "take-down"}
        onCancel={() => setModal(null)}
        onConfirm={onConfirm}
      />
    </div>
  );
}
```

- [ ] **Step 3: Typecheck + smoke**

```bash
pnpm typecheck && pnpm dev
```

Visit `/admin/communities` as moderator — list + take-down/restore buttons present.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/app/admin/communities/
git commit -m "feat(admin/web): /admin/communities list + detail with take-down"
```

---

### Task 26: /admin/listings list + detail pages

**Files:**
- Create: `apps/web/src/app/admin/listings/page.tsx`
- Create: `apps/web/src/app/admin/listings/[id]/page.tsx`

- [ ] **Step 1: Create the list page**

`apps/web/src/app/admin/listings/page.tsx`:

```tsx
"use client";
import Link from "next/link";
import { useEffect, useState } from "react";

import { ReasonModal } from "@/components/ReasonModal";
import {
  listAdminListings, restoreAdminListing, takeDownAdminListing,
} from "@/lib/api";
import type { AdminListingRow } from "@/lib/types";

export default function AdminListingsPage() {
  const [rows, setRows] = useState<AdminListingRow[]>([]);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<string>("");
  const [modal, setModal] = useState<
    | null
    | { kind: "take-down"; row: AdminListingRow }
    | { kind: "restore"; row: AdminListingRow }
  >(null);

  const reload = () =>
    listAdminListings({
      q: q || undefined,
      availability_status: status || undefined,
    }).then(setRows);

  useEffect(() => { reload(); /* eslint-disable-line */ }, [status]);

  const onConfirm = async (reason: string) => {
    if (!modal) return;
    if (modal.kind === "take-down") await takeDownAdminListing(modal.row.id, reason);
    if (modal.kind === "restore")   await restoreAdminListing(modal.row.id, reason);
    setModal(null);
    await reload();
  };

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-8">
      <h1 className="font-serif text-2xl text-stone-900">Listings</h1>

      <div className="flex items-center gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") reload(); }}
          placeholder="Search title"
          className="rounded border border-stone-300 px-3 py-1.5 text-sm"
        />
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="rounded border border-stone-300 px-3 py-1.5 text-sm"
        >
          <option value="">All statuses</option>
          <option value="available">available</option>
          <option value="claimed">claimed</option>
          <option value="completed">completed</option>
          <option value="removed">removed</option>
        </select>
        <button onClick={() => reload()} className="rounded bg-amber-600 px-3 py-1.5 text-sm text-white">
          Search
        </button>
      </div>

      <div className="overflow-x-auto rounded-lg border border-stone-200 bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-stone-50 text-left text-xs uppercase tracking-wider text-stone-500">
            <tr>
              <th className="px-4 py-2">Title</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2">Household</th>
              <th className="px-4 py-2">Created</th>
              <th className="px-4 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100">
            {rows.map((l) => (
              <tr key={l.id} className="hover:bg-stone-50">
                <td className="px-4 py-2">
                  <Link href={`/admin/listings/${l.id}`} className="hover:underline">
                    {l.title}
                  </Link>
                </td>
                <td className="px-4 py-2 text-stone-700">{l.availability_status}</td>
                <td className="px-4 py-2 font-mono text-xs text-stone-500">
                  {l.household_id.slice(0, 8)}
                </td>
                <td className="px-4 py-2 text-stone-500">
                  {new Date(l.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-2 text-right">
                  {l.deleted_at ? (
                    <button
                      onClick={() => setModal({ kind: "restore", row: l })}
                      className="rounded bg-stone-100 px-2 py-1 text-xs hover:bg-stone-200"
                    >
                      Restore
                    </button>
                  ) : (
                    <button
                      onClick={() => setModal({ kind: "take-down", row: l })}
                      className="rounded bg-red-100 px-2 py-1 text-xs text-red-800 hover:bg-red-200"
                    >
                      Take down
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ReasonModal
        open={modal !== null}
        title={
          modal?.kind === "take-down" ? `Take down "${modal.row.title}"` :
          modal?.kind === "restore"   ? `Restore "${modal.row.title}"` : ""
        }
        actionLabel={modal?.kind === "take-down" ? "Take down" : "Restore"}
        destructive={modal?.kind === "take-down"}
        onCancel={() => setModal(null)}
        onConfirm={onConfirm}
      />
    </div>
  );
}
```

- [ ] **Step 2: Create the detail page**

`apps/web/src/app/admin/listings/[id]/page.tsx`:

```tsx
"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ReasonModal } from "@/components/ReasonModal";
import {
  getAdminListing, restoreAdminListing, takeDownAdminListing,
} from "@/lib/api";
import type { AdminListingDetail } from "@/lib/types";

export default function AdminListingDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [l, setL] = useState<AdminListingDetail | null>(null);
  const [modal, setModal] = useState<null | "take-down" | "restore">(null);
  const reload = () => getAdminListing(id).then(setL);

  useEffect(() => { reload(); /* eslint-disable-line */ }, [id]);

  if (!l) return <div className="p-8 text-stone-500">Loading…</div>;

  const onConfirm = async (reason: string) => {
    if (modal === "take-down") await takeDownAdminListing(id, reason);
    if (modal === "restore")   await restoreAdminListing(id, reason);
    setModal(null);
    await reload();
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-8">
      <Link href="/admin/listings" className="text-sm text-stone-500 hover:underline">
        ← Back to listings
      </Link>

      <header className="flex items-start justify-between">
        <div>
          <h1 className="font-serif text-2xl text-stone-900">{l.title}</h1>
          <p className="text-sm text-stone-500">
            Status: {l.availability_status} ·{" "}
            {l.deleted_at ? "Taken down" : "Live"}
          </p>
        </div>
        {l.deleted_at ? (
          <button
            onClick={() => setModal("restore")}
            className="rounded bg-stone-100 px-3 py-1.5 text-sm hover:bg-stone-200"
          >
            Restore
          </button>
        ) : (
          <button
            onClick={() => setModal("take-down")}
            className="rounded bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-700"
          >
            Take down
          </button>
        )}
      </header>

      <section className="rounded-lg border border-stone-200 bg-white p-5 text-sm">
        <dl className="grid grid-cols-2 gap-y-2">
          <dt className="text-stone-500">Description</dt><dd>{l.description ?? "—"}</dd>
          <dt className="text-stone-500">Item</dt>
          <dd className="font-mono text-xs">{l.item_id}</dd>
          <dt className="text-stone-500">Owner household</dt>
          <dd className="font-mono text-xs">{l.household_id}</dd>
          <dt className="text-stone-500">Exchange types</dt>
          <dd>{l.allowed_exchange_types.join(", ")}</dd>
          <dt className="text-stone-500">Qty available</dt>
          <dd>{l.quantity_available}</dd>
          <dt className="text-stone-500">Created</dt>
          <dd>{new Date(l.created_at).toLocaleString()}</dd>
          {l.deleted_at && (
            <>
              <dt className="text-stone-500">Taken down</dt>
              <dd>{new Date(l.deleted_at).toLocaleString()}</dd>
            </>
          )}
        </dl>
      </section>

      <section>
        <h2 className="mb-2 font-serif text-lg text-stone-900">
          Shared with ({l.shared_with_communities.length})
        </h2>
        <ul className="space-y-1 font-mono text-xs text-stone-500">
          {l.shared_with_communities.length === 0 && (
            <li className="text-stone-400">None — radius visibility only.</li>
          )}
          {l.shared_with_communities.map((cid) => (
            <li key={cid}>
              <Link href={`/admin/communities/${cid}`} className="hover:underline">
                {cid}
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <ReasonModal
        open={modal !== null}
        title={modal === "take-down" ? `Take down "${l.title}"` : `Restore "${l.title}"`}
        actionLabel={modal === "take-down" ? "Take down" : "Restore"}
        destructive={modal === "take-down"}
        onCancel={() => setModal(null)}
        onConfirm={onConfirm}
      />
    </div>
  );
}
```

- [ ] **Step 3: Typecheck + commit**

```bash
pnpm typecheck
git add apps/web/src/app/admin/listings/
git commit -m "feat(admin/web): /admin/listings list + detail with take-down"
```

---

### Task 27: /admin/audit-log page

**Files:**
- Create: `apps/web/src/app/admin/audit-log/page.tsx`

- [ ] **Step 1: Create the page**

`apps/web/src/app/admin/audit-log/page.tsx`:

```tsx
"use client";
import { useEffect, useState } from "react";

import { listAdminAuditLog } from "@/lib/api";
import type { AuditLogEntry } from "@/lib/types";

const PAGE_SIZE = 50;

export default function AuditLogPage() {
  const [rows, setRows] = useState<AuditLogEntry[]>([]);
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [actionPrefix, setActionPrefix] = useState("");
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const reload = () =>
    listAdminAuditLog({
      actor_user_id: actor || undefined,
      action: action || undefined,
      action_prefix: actionPrefix || undefined,
      limit: PAGE_SIZE, offset,
    }).then(setRows);

  useEffect(() => { reload(); /* eslint-disable-line */ }, [offset]);

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-8">
      <h1 className="font-serif text-2xl text-stone-900">Audit log</h1>

      <div className="flex flex-wrap items-center gap-2">
        <input
          value={actor}
          onChange={(e) => setActor(e.target.value)}
          placeholder="actor user UUID"
          className="rounded border border-stone-300 px-3 py-1.5 text-sm font-mono"
        />
        <input
          value={action}
          onChange={(e) => setAction(e.target.value)}
          placeholder="exact action"
          className="rounded border border-stone-300 px-3 py-1.5 text-sm"
        />
        <input
          value={actionPrefix}
          onChange={(e) => setActionPrefix(e.target.value)}
          placeholder="action prefix (e.g. admin.user)"
          className="rounded border border-stone-300 px-3 py-1.5 text-sm"
        />
        <button onClick={() => { setOffset(0); reload(); }} className="rounded bg-amber-600 px-3 py-1.5 text-sm text-white">
          Filter
        </button>
      </div>

      <div className="rounded-lg border border-stone-200 bg-white">
        <ul className="divide-y divide-stone-100 text-sm">
          {rows.length === 0 && <li className="p-4 text-stone-400">No entries.</li>}
          {rows.map((r) => (
            <li key={r.id} className="px-4 py-2">
              <button
                onClick={() => toggle(r.id)}
                className="w-full text-left"
              >
                <div className="flex items-baseline justify-between gap-4">
                  <div className="text-stone-800">{r.action}</div>
                  <div className="text-xs text-stone-400">
                    {new Date(r.created_at).toLocaleString()}
                  </div>
                </div>
                <div className="text-xs text-stone-500">
                  actor <span className="font-mono">{r.actor_user_id?.slice(0, 8) ?? "—"}</span>
                  {r.target_type && (
                    <> · target {r.target_type}{" "}
                      <span className="font-mono">{r.target_id?.slice(0, 8)}</span>
                    </>
                  )}
                </div>
              </button>
              {expanded.has(r.id) && (
                <pre className="mt-2 max-h-60 overflow-auto rounded bg-stone-50 px-2 py-1 text-[11px] text-stone-700">
                  {JSON.stringify(r.payload, null, 2)}
                </pre>
              )}
            </li>
          ))}
        </ul>
      </div>

      <div className="flex items-center justify-between text-sm">
        <button
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          className="rounded border border-stone-300 px-3 py-1 disabled:opacity-50"
        >
          ← Prev
        </button>
        <span className="text-stone-500">offset {offset}</span>
        <button
          disabled={rows.length < PAGE_SIZE}
          onClick={() => setOffset(offset + PAGE_SIZE)}
          className="rounded border border-stone-300 px-3 py-1 disabled:opacity-50"
        >
          Next →
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck + commit**

```bash
pnpm typecheck
git add apps/web/src/app/admin/audit-log/page.tsx
git commit -m "feat(admin/web): /admin/audit-log page with filters + pagination"
```

---

### Task 28: /admin/settings list + detail pages

**Files:**
- Create: `apps/web/src/app/admin/settings/page.tsx`
- Create: `apps/web/src/app/admin/settings/[key]/page.tsx`

- [ ] **Step 1: Create the list page**

`apps/web/src/app/admin/settings/page.tsx`:

```tsx
"use client";
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  clearAdminSettingGlobal, listAdminSettings, setAdminSettingGlobal,
} from "@/lib/api";
import type { GlobalSettingRow } from "@/lib/types";

function ValueWidget({
  row, onSave,
}: { row: GlobalSettingRow; onSave: (v: unknown) => Promise<void> }) {
  const [local, setLocal] = useState<unknown>(row.current_global);

  const commit = async () => {
    let v = local;
    if (row.spec.type === "int")  v = Number(v);
    if (row.spec.type === "bool") v = Boolean(v);
    await onSave(v);
  };

  if (row.spec.type === "bool") {
    return (
      <input
        type="checkbox"
        checked={Boolean(local)}
        onChange={async (e) => { setLocal(e.target.checked); await onSave(e.target.checked); }}
      />
    );
  }
  if (row.spec.type === "int") {
    return (
      <div className="flex gap-1">
        <input
          type="number"
          value={String(local ?? "")}
          onChange={(e) => setLocal(e.target.value)}
          className="w-24 rounded border border-stone-300 px-2 py-0.5 text-sm"
        />
        <button onClick={commit} className="rounded bg-amber-600 px-2 text-xs text-white">save</button>
      </div>
    );
  }
  // str (default)
  return (
    <div className="flex gap-1">
      <input
        type="text"
        value={String(local ?? "")}
        onChange={(e) => setLocal(e.target.value)}
        className="w-48 rounded border border-stone-300 px-2 py-0.5 text-sm"
      />
      <button onClick={commit} className="rounded bg-amber-600 px-2 text-xs text-white">save</button>
    </div>
  );
}

export default function AdminSettingsPage() {
  const [rows, setRows] = useState<GlobalSettingRow[]>([]);

  const reload = () => listAdminSettings().then(setRows);
  useEffect(() => { reload(); }, []);

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-8">
      <h1 className="font-serif text-2xl text-stone-900">Settings</h1>
      <p className="text-sm text-stone-500">
        Globals are editable here. Click a key to manage per-household / per-user overrides.
      </p>

      <div className="overflow-x-auto rounded-lg border border-stone-200 bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-stone-50 text-left text-xs uppercase tracking-wider text-stone-500">
            <tr>
              <th className="px-4 py-2">Key</th>
              <th className="px-4 py-2">Type</th>
              <th className="px-4 py-2">Scopes</th>
              <th className="px-4 py-2">Global value</th>
              <th className="px-4 py-2">Overrides</th>
              <th className="px-4 py-2 text-right">Reset</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100">
            {rows.map((row) => (
              <tr key={row.key} className="hover:bg-stone-50">
                <td className="px-4 py-2">
                  <Link href={`/admin/settings/${encodeURIComponent(row.key)}`} className="hover:underline">
                    {row.key}
                  </Link>
                  <div className="text-xs text-stone-400">{row.spec.description}</div>
                </td>
                <td className="px-4 py-2 text-stone-500">{row.spec.type}</td>
                <td className="px-4 py-2 text-stone-500 text-xs">{row.spec.scopes.join(", ")}</td>
                <td className="px-4 py-2">
                  {row.spec.scopes.includes("global") ? (
                    <ValueWidget
                      row={row}
                      onSave={async (v) => {
                        await setAdminSettingGlobal(row.key, v);
                        await reload();
                      }}
                    />
                  ) : (
                    <span className="text-stone-400 text-xs">no global scope</span>
                  )}
                </td>
                <td className="px-4 py-2 text-stone-500 text-xs">
                  hh: {row.household_override_count} · user: {row.user_override_count}
                </td>
                <td className="px-4 py-2 text-right">
                  {row.has_global_override && (
                    <button
                      onClick={async () => { await clearAdminSettingGlobal(row.key); await reload(); }}
                      className="rounded bg-stone-100 px-2 py-1 text-xs hover:bg-stone-200"
                    >
                      Clear
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create the detail page**

`apps/web/src/app/admin/settings/[key]/page.tsx`:

```tsx
"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  clearAdminSettingHousehold, clearAdminSettingUser, getAdminSetting,
  setAdminSettingHousehold, setAdminSettingUser,
} from "@/lib/api";
import type { SettingDetail } from "@/lib/types";

export default function AdminSettingDetailPage() {
  const { key } = useParams<{ key: string }>();
  const [detail, setDetail] = useState<SettingDetail | null>(null);
  const [newHh, setNewHh] = useState({ id: "", value: "" });
  const [newU,  setNewU]  = useState({ id: "", value: "" });

  const reload = () => getAdminSetting(decodeURIComponent(key)).then(setDetail);
  useEffect(() => { reload(); /* eslint-disable-line */ }, [key]);

  if (!detail) return <div className="p-8 text-stone-500">Loading…</div>;

  const parseValue = (raw: string): unknown => {
    if (detail.spec.type === "bool") return raw === "true" || raw === "1";
    if (detail.spec.type === "int")  return Number(raw);
    return raw;
  };

  const supportsHh = detail.spec.scopes.includes("household");
  const supportsU  = detail.spec.scopes.includes("user");

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-8">
      <Link href="/admin/settings" className="text-sm text-stone-500 hover:underline">
        ← Back to settings
      </Link>

      <header>
        <h1 className="font-serif text-2xl text-stone-900">{detail.key}</h1>
        <p className="text-sm text-stone-500">{detail.spec.description}</p>
        <p className="text-xs text-stone-400 mt-1">
          type {detail.spec.type} · scopes {detail.spec.scopes.join(", ")} ·{" "}
          {detail.spec.public ? "PUBLIC" : "private"}
        </p>
      </header>

      <section className="rounded-lg border border-stone-200 bg-white p-5 text-sm">
        <h2 className="font-serif text-base text-stone-900">Global</h2>
        <p className="mt-1">
          Current: <code>{JSON.stringify(detail.current_global)}</code>
          {detail.has_global_override ? " (overridden)" : " (registry default)"}
        </p>
      </section>

      {supportsHh && (
        <section className="rounded-lg border border-stone-200 bg-white p-5 text-sm">
          <h2 className="font-serif text-base text-stone-900">
            Household overrides ({detail.household_overrides.length})
          </h2>
          <ul className="mt-2 space-y-1">
            {detail.household_overrides.map((o) => (
              <li key={o.household_id} className="flex items-center justify-between font-mono text-xs">
                <span>{o.household_id} → {JSON.stringify(o.value)}</span>
                <button
                  onClick={async () => {
                    await clearAdminSettingHousehold(detail.key, o.household_id);
                    await reload();
                  }}
                  className="rounded bg-stone-100 px-2 py-0.5 text-xs hover:bg-stone-200"
                >
                  clear
                </button>
              </li>
            ))}
          </ul>
          <div className="mt-3 flex gap-2">
            <input
              placeholder="household UUID"
              value={newHh.id}
              onChange={(e) => setNewHh({ ...newHh, id: e.target.value })}
              className="flex-1 rounded border border-stone-300 px-2 py-1 text-xs font-mono"
            />
            <input
              placeholder="value"
              value={newHh.value}
              onChange={(e) => setNewHh({ ...newHh, value: e.target.value })}
              className="w-32 rounded border border-stone-300 px-2 py-1 text-xs"
            />
            <button
              onClick={async () => {
                await setAdminSettingHousehold(detail.key, newHh.id, parseValue(newHh.value));
                setNewHh({ id: "", value: "" });
                await reload();
              }}
              className="rounded bg-amber-600 px-3 text-xs text-white"
            >
              Add
            </button>
          </div>
        </section>
      )}

      {supportsU && (
        <section className="rounded-lg border border-stone-200 bg-white p-5 text-sm">
          <h2 className="font-serif text-base text-stone-900">
            User overrides ({detail.user_overrides.length})
          </h2>
          <ul className="mt-2 space-y-1">
            {detail.user_overrides.map((o) => (
              <li key={o.user_id} className="flex items-center justify-between font-mono text-xs">
                <span>{o.user_id} → {JSON.stringify(o.value)}</span>
                <button
                  onClick={async () => {
                    await clearAdminSettingUser(detail.key, o.user_id);
                    await reload();
                  }}
                  className="rounded bg-stone-100 px-2 py-0.5 text-xs hover:bg-stone-200"
                >
                  clear
                </button>
              </li>
            ))}
          </ul>
          <div className="mt-3 flex gap-2">
            <input
              placeholder="user UUID"
              value={newU.id}
              onChange={(e) => setNewU({ ...newU, id: e.target.value })}
              className="flex-1 rounded border border-stone-300 px-2 py-1 text-xs font-mono"
            />
            <input
              placeholder="value"
              value={newU.value}
              onChange={(e) => setNewU({ ...newU, value: e.target.value })}
              className="w-32 rounded border border-stone-300 px-2 py-1 text-xs"
            />
            <button
              onClick={async () => {
                await setAdminSettingUser(detail.key, newU.id, parseValue(newU.value));
                setNewU({ id: "", value: "" });
                await reload();
              }}
              className="rounded bg-amber-600 px-3 text-xs text-white"
            >
              Add
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Typecheck + commit**

```bash
pnpm typecheck
git add apps/web/src/app/admin/settings/
git commit -m "feat(admin/web): /admin/settings list + detail (all 3 scopes)"
```

---

### Task 29: /admin/flags list + detail pages

**Files:**
- Create: `apps/web/src/app/admin/flags/page.tsx`
- Create: `apps/web/src/app/admin/flags/[key]/page.tsx`

- [ ] **Step 1: Create the list page**

`apps/web/src/app/admin/flags/page.tsx`:

```tsx
"use client";
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  createAdminFlag, deleteAdminFlag, listAdminFlags, patchAdminFlag,
} from "@/lib/api";
import type { FeatureFlag } from "@/lib/types";

export default function AdminFlagsPage() {
  const [rows, setRows] = useState<FeatureFlag[]>([]);
  const [creating, setCreating] = useState(false);
  const [newKey, setNewKey] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [error, setError] = useState<string | null>(null);

  const reload = () => listAdminFlags().then(setRows);
  useEffect(() => { reload(); }, []);

  const create = async () => {
    setError(null);
    try {
      await createAdminFlag({ key: newKey, description: newDesc });
      setNewKey(""); setNewDesc(""); setCreating(false);
      await reload();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Create failed");
    }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-8">
      <div className="flex items-center justify-between">
        <h1 className="font-serif text-2xl text-stone-900">Feature flags</h1>
        <button
          onClick={() => setCreating(!creating)}
          className="rounded bg-amber-600 px-3 py-1.5 text-sm text-white hover:bg-amber-700"
        >
          {creating ? "Cancel" : "+ New flag"}
        </button>
      </div>

      {creating && (
        <div className="rounded-lg border border-stone-200 bg-white p-4 space-y-2">
          <input
            placeholder="key (e.g. ai.experimental.feature.enabled)"
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
            className="w-full rounded border border-stone-300 px-3 py-1.5 text-sm"
          />
          <input
            placeholder="description"
            value={newDesc}
            onChange={(e) => setNewDesc(e.target.value)}
            className="w-full rounded border border-stone-300 px-3 py-1.5 text-sm"
          />
          <button onClick={create} className="rounded bg-amber-600 px-3 py-1 text-sm text-white">
            Create
          </button>
          {error && <div className="text-xs text-red-700">{error}</div>}
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-stone-200 bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-stone-50 text-left text-xs uppercase tracking-wider text-stone-500">
            <tr>
              <th className="px-4 py-2">Key</th>
              <th className="px-4 py-2">Description</th>
              <th className="px-4 py-2">Enabled</th>
              <th className="px-4 py-2">Rollout %</th>
              <th className="px-4 py-2">Overrides</th>
              <th className="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100">
            {rows.map((f) => (
              <tr key={f.key} className="hover:bg-stone-50">
                <td className="px-4 py-2">
                  <Link href={`/admin/flags/${encodeURIComponent(f.key)}`} className="hover:underline font-mono text-xs">
                    {f.key}
                  </Link>
                </td>
                <td className="px-4 py-2 text-stone-500">{f.description ?? "—"}</td>
                <td className="px-4 py-2">
                  <input
                    type="checkbox"
                    checked={f.enabled_globally}
                    onChange={async (e) => {
                      await patchAdminFlag(f.key, { enabled_globally: e.target.checked });
                      await reload();
                    }}
                  />
                </td>
                <td className="px-4 py-2">
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={f.rollout_percent}
                    onChange={async (e) => {
                      await patchAdminFlag(f.key, { rollout_percent: Number(e.target.value) });
                      await reload();
                    }}
                    className="w-32"
                  />
                  <span className="ml-2 text-xs text-stone-500">{f.rollout_percent}%</span>
                </td>
                <td className="px-4 py-2 text-xs text-stone-500">
                  hh: {f.household_override_count} · user: {f.user_override_count}
                </td>
                <td className="px-4 py-2 text-right">
                  <button
                    onClick={async () => {
                      if (confirm(`Delete flag ${f.key}? Soft-delete; restore is not currently supported.`)) {
                        await deleteAdminFlag(f.key);
                        await reload();
                      }
                    }}
                    className="rounded bg-stone-100 px-2 py-1 text-xs hover:bg-stone-200"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create the detail page**

`apps/web/src/app/admin/flags/[key]/page.tsx`:

```tsx
"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
  getAdminFlag, setAdminFlagHouseholdOverride, setAdminFlagUserOverride,
} from "@/lib/api";
import type { FeatureFlagDetail } from "@/lib/types";

export default function AdminFlagDetailPage() {
  const { key } = useParams<{ key: string }>();
  const [flag, setFlag] = useState<FeatureFlagDetail | null>(null);
  const [newHh, setNewHh] = useState({ id: "", enabled: true });
  const [newU,  setNewU]  = useState({ id: "", enabled: true });

  const reload = () => getAdminFlag(decodeURIComponent(key)).then(setFlag);
  useEffect(() => { reload(); /* eslint-disable-line */ }, [key]);

  if (!flag) return <div className="p-8 text-stone-500">Loading…</div>;

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-8">
      <Link href="/admin/flags" className="text-sm text-stone-500 hover:underline">
        ← Back to flags
      </Link>

      <header>
        <h1 className="font-serif text-2xl text-stone-900 font-mono break-all">{flag.key}</h1>
        <p className="text-sm text-stone-500">{flag.description ?? "—"}</p>
      </header>

      <section className="rounded-lg border border-stone-200 bg-white p-5 text-sm">
        <dl className="grid grid-cols-2 gap-y-2">
          <dt className="text-stone-500">Global enabled</dt>
          <dd>{flag.enabled_globally ? "yes" : "no"}</dd>
          <dt className="text-stone-500">Rollout %</dt>
          <dd>{flag.rollout_percent}</dd>
        </dl>
      </section>

      <section className="rounded-lg border border-stone-200 bg-white p-5 text-sm">
        <h2 className="font-serif text-base text-stone-900">
          Household overrides ({flag.household_overrides.length})
        </h2>
        <ul className="mt-2 space-y-1">
          {flag.household_overrides.map((o) => (
            <li key={o.id} className="font-mono text-xs">
              {o.household_id} → {o.enabled ? "ON" : "OFF"}
            </li>
          ))}
        </ul>
        <div className="mt-3 flex gap-2">
          <input
            placeholder="household UUID"
            value={newHh.id}
            onChange={(e) => setNewHh({ ...newHh, id: e.target.value })}
            className="flex-1 rounded border border-stone-300 px-2 py-1 text-xs font-mono"
          />
          <select
            value={String(newHh.enabled)}
            onChange={(e) => setNewHh({ ...newHh, enabled: e.target.value === "true" })}
            className="rounded border border-stone-300 px-2 py-1 text-xs"
          >
            <option value="true">ON</option>
            <option value="false">OFF</option>
          </select>
          <button
            onClick={async () => {
              await setAdminFlagHouseholdOverride(flag.key, newHh.id, newHh.enabled);
              setNewHh({ id: "", enabled: true });
              await reload();
            }}
            className="rounded bg-amber-600 px-3 text-xs text-white"
          >
            Add
          </button>
        </div>
      </section>

      <section className="rounded-lg border border-stone-200 bg-white p-5 text-sm">
        <h2 className="font-serif text-base text-stone-900">
          User overrides ({flag.user_overrides.length})
        </h2>
        <ul className="mt-2 space-y-1">
          {flag.user_overrides.map((o) => (
            <li key={o.id} className="font-mono text-xs">
              {o.user_id} → {o.enabled ? "ON" : "OFF"}
            </li>
          ))}
        </ul>
        <div className="mt-3 flex gap-2">
          <input
            placeholder="user UUID"
            value={newU.id}
            onChange={(e) => setNewU({ ...newU, id: e.target.value })}
            className="flex-1 rounded border border-stone-300 px-2 py-1 text-xs font-mono"
          />
          <select
            value={String(newU.enabled)}
            onChange={(e) => setNewU({ ...newU, enabled: e.target.value === "true" })}
            className="rounded border border-stone-300 px-2 py-1 text-xs"
          >
            <option value="true">ON</option>
            <option value="false">OFF</option>
          </select>
          <button
            onClick={async () => {
              await setAdminFlagUserOverride(flag.key, newU.id, newU.enabled);
              setNewU({ id: "", enabled: true });
              await reload();
            }}
            className="rounded bg-amber-600 px-3 text-xs text-white"
          >
            Add
          </button>
        </div>
      </section>
    </div>
  );
}
```

- [ ] **Step 3: Typecheck + commit**

```bash
pnpm typecheck
git add apps/web/src/app/admin/flags/
git commit -m "feat(admin/web): /admin/flags list + detail (overrides + rollout slider)"
```

---

### Task 30: /admin/banner page + final test sweep

**Files:**
- Create: `apps/web/src/app/admin/banner/page.tsx`

- [ ] **Step 1: Create the banner editor**

`apps/web/src/app/admin/banner/page.tsx`:

```tsx
"use client";
import { useEffect, useState } from "react";

import {
  clearAdminSettingGlobal, getAdminSetting, setAdminSettingGlobal,
} from "@/lib/api";

export default function AdminBannerPage() {
  const [message, setMessage] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getAdminSetting("maintenance_message").then((d) => {
      setMessage(String(d.current_global ?? ""));
    });
  }, []);

  const save = async () => {
    await setAdminSettingGlobal("maintenance_message", message);
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  };

  const clear = async () => {
    await clearAdminSettingGlobal("maintenance_message");
    setMessage("");
  };

  return (
    <div className="mx-auto max-w-2xl space-y-6 p-8">
      <h1 className="font-serif text-2xl text-stone-900">Maintenance banner</h1>
      <p className="text-sm text-stone-500">
        Non-empty text shows as a banner across every page (public — no auth needed).
      </p>

      <textarea
        rows={4}
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        placeholder="e.g. Scheduled maintenance Sun 2am UTC"
        className="w-full rounded border border-stone-300 px-3 py-2 text-sm"
      />

      <div className="flex items-center gap-3">
        <button onClick={save} className="rounded bg-amber-600 px-4 py-1.5 text-sm text-white">
          Save
        </button>
        <button onClick={clear} className="rounded bg-stone-100 px-4 py-1.5 text-sm">
          Clear
        </button>
        {saved && <span className="text-xs text-green-700">Saved ✓</span>}
      </div>

      <section>
        <h2 className="mb-2 font-serif text-base text-stone-900">Preview</h2>
        {message ? (
          <div className="w-full rounded border border-amber-200 bg-amber-50 px-4 py-2 text-center text-sm text-amber-900">
            {message}
          </div>
        ) : (
          <p className="text-xs text-stone-400">Empty — no banner shown.</p>
        )}
      </section>
    </div>
  );
}
```

- [ ] **Step 2: Full frontend typecheck + build**

```bash
cd apps/web
pnpm typecheck
pnpm build
```

Expected: typecheck clean; build succeeds; all `/admin/*` routes appear in the route list.

- [ ] **Step 3: Full backend test sweep**

```bash
cd apps/backend
uv run pytest -q 2>&1 | tail -5
uv run ruff check .
uv run mypy app 2>&1 | tail -5
```

Expected: pytest green (no new failures); ruff clean; mypy clean for new files (pre-existing errors in unrelated files are out of scope).

- [ ] **Step 4: End-to-end smoke (manual)**

In separate terminals:
```bash
./frugal up        # whole stack
```

In `apps/backend/.env`, set:
```
ADMIN_EMAIL=youremail@example.com
ADMIN_PASSWORD=temp-bootstrap-pw
ADMIN_DISPLAY_NAME=Test Admin
```

Restart the backend → check log line "bootstrap admin created" (first run).

In the browser: visit `http://localhost:3000`, log in as `ADMIN_EMAIL`. You should see:
- ADMIN badge next to your name
- "Admin" section in the sidebar with all 8 links
- Each subpage loads:
  - `/admin` → tile grid + recent audit
  - `/admin/users` → role dropdown + lock/active buttons
  - `/admin/communities`, `/admin/listings` → take-down actions
  - `/admin/audit-log` → entries from the bootstrap + any actions you took
  - `/admin/settings` → all registry keys with inline editor; click into one → override editors
  - `/admin/flags` → seeded flags + create-new + rollout slider
  - `/admin/banner` → set a message → reload another page → banner appears

Promote a second user to moderator via `/admin/users` → log in as them in an incognito window → confirm: Admin section is visible, but Settings/Flags/Banner items are hidden; navigating to `/admin/settings` direct redirects (or 403 from API).

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/app/admin/banner/page.tsx
git commit -m "feat(admin/web): /admin/banner editor + final smoke verification"
```

---

## Plan complete

All 30 tasks done →
- 14 new backend tests files (~80 test functions)
- 7 new routers, 5 new service modules, 4 new model classes
- 2 migrations (`0006_admin_role`, `0007_app_settings`)
- 4 new shared frontend components, 13 new `/admin/*` pages
- Sidebar + maintenance banner integrated into existing chrome

The branch is ready for the standard subagent-driven-development closing review → `superpowers:finishing-a-development-branch`.
