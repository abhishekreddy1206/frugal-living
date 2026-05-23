# Real Authentication & Multi-Household Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded dev-auth stub with real custom email+password authentication, server-side sessions via httpOnly cookie, and full multi-household support (active-household model, switcher, invite-by-link) — so people have separate accounts and Tier B Phase 3 is unblocked.

**Architecture:** Custom FastAPI auth, server-side sessions stored in a new `core.sessions` table (SHA-256 token hash; raw token in a `Lax` httpOnly cookie); rewires only `app/auth.py`'s two FastAPI dependencies so every existing router/service is untouched. The 213 existing tests are preserved by relocating the dev user/household seeding into `conftest.py` and installing `app.dependency_overrides`, with new auth-flow tests opting out via a `@pytest.mark.real_auth` marker.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy 2.0 / Alembic / PostgreSQL / `passlib[bcrypt]` (already in `pyproject.toml`) / `secrets` / `hashlib` / pytest. Frontend: Next.js 14 / TypeScript / Tailwind. Package managers: `uv` (backend), `pnpm` (frontend).

**Spec:** `docs/superpowers/specs/2026-05-22-real-auth-multi-household-design.md`

All backend commands run from `apps/backend/`; all frontend commands from `apps/web/`. Postgres must be running. Implement in an isolated worktree.

---

### Task 1: Cookie & throttling settings

**Files:**
- Modify: `apps/backend/app/config.py`

- [ ] **Step 1: Add settings**

Replace the entire body of `apps/backend/app/config.py` with:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    anthropic_api_key: str = "missing"  # unused while llm.py routes through the Claude Code CLI
    jwt_secret: str = "change-me"
    env: str = "local"
    log_level: str = "INFO"

    # Content ingestion
    youtube_api_key: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "frugal-living-dev/0.1"

    # Voice (optional)
    openai_api_key: str = ""

    # Auth — session cookie
    session_cookie_name: str = "hearth_session"
    session_cookie_samesite: str = "lax"  # "lax" in dev/same-site prod; "none" if API on a different registrable domain
    session_cookie_secure: bool = False  # False in local; True in prod (and required when samesite="none")
    session_max_age_days: int = 30

    # Auth — login throttling (per-email)
    login_lockout_threshold: int = 5
    login_lockout_minutes: int = 15

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")


settings = Settings()
```

- [ ] **Step 2: Confirm settings load**

Run: `uv run python -c "from app.config import settings; print(settings.session_cookie_name, settings.session_max_age_days, settings.login_lockout_threshold)"`
Expected: `hearth_session 30 5`.

- [ ] **Step 3: Commit**

```bash
git add apps/backend/app/config.py
git commit -m "feat(auth): add session cookie and login throttling settings"
```

---

### Task 2: Auth models (`Session`, `HouseholdInvite`, User columns) + migration `0004`

**Files:**
- Modify: `apps/backend/app/models/core.py`
- Create: `apps/backend/alembic/versions/0004_real_auth.py`
- Test: `apps/backend/tests/test_auth_models.py`

- [ ] **Step 1: Add the User column fields**

In `apps/backend/app/models/core.py`, inside the `User` class, immediately after the existing `metadata_` field, add these three lines (and leave the `household_memberships` relationship line right after them, unchanged):

```python
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 2: Add the `Session` and `HouseholdInvite` models**

In the same file `apps/backend/app/models/core.py`, append these two classes to the end of the file (after `AuditLog`):

```python
class Session(Base):
    """Server-side auth session. Created on login, revoked on logout/password-change.

    Deliberate deviation from Rule 4 (TimestampMixin + deleted_at): sessions are
    ephemeral auth infrastructure, following the same pattern as core.events and
    core.audit_log. Lifecycle is expressed by `revoked_at` + `expires_at`.
    """
    __tablename__ = "sessions"
    __table_args__ = (
        Index("idx_sessions_user", "user_id"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    active_household_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)


class HouseholdInvite(Base):
    """Pending invite to join a household. The raw token is shared by the inviter
    out-of-band (link/text); only the SHA-256 hash is stored here.

    Same infra-table rationale as Session for omitting TimestampMixin: lifecycle
    is `expires_at` / `accepted_at` / `revoked_at`.
    """
    __tablename__ = "household_invites"
    __table_args__ = (
        Index("idx_household_invites_household", "household_id"),
        {"schema": "core"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.households.id"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="member", nullable=False)
    # member | viewer
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=False
    )
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.users.id"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
```

- [ ] **Step 3: Write the migration**

Create `apps/backend/alembic/versions/0004_real_auth.py`:

```python
"""real auth: sessions, household_invites, user auth columns

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-22

"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # core.users — three new columns for auth
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="core",
    )
    op.add_column(
        "users",
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
        schema="core",
    )
    op.add_column(
        "users",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        schema="core",
    )

    # core.sessions
    op.create_table(
        "sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("active_household_id", sa.UUID(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["core.users.id"]),
        sa.ForeignKeyConstraint(["active_household_id"], ["core.households.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
        schema="core",
    )
    op.create_index("idx_sessions_user", "sessions", ["user_id"], unique=False, schema="core")

    # core.household_invites
    op.create_table(
        "household_invites",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("household_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by_user_id", sa.UUID(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["core.households.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["core.users.id"]),
        sa.ForeignKeyConstraint(["accepted_by_user_id"], ["core.users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
        schema="core",
    )
    op.create_index(
        "idx_household_invites_household", "household_invites",
        ["household_id"], unique=False, schema="core",
    )


def downgrade() -> None:
    op.drop_index("idx_household_invites_household", table_name="household_invites", schema="core")
    op.drop_table("household_invites", schema="core")
    op.drop_index("idx_sessions_user", table_name="sessions", schema="core")
    op.drop_table("sessions", schema="core")
    op.drop_column("users", "locked_until", schema="core")
    op.drop_column("users", "failed_login_count", schema="core")
    op.drop_column("users", "email_verified", schema="core")
```

- [ ] **Step 4: Apply the migration**

Run: `uv run alembic upgrade head`
Expected: ends with `Running upgrade 0003 -> 0004, real auth: sessions, household_invites, user auth columns`.

- [ ] **Step 5: Write the model test**

Create `apps/backend/tests/test_auth_models.py`:

```python
"""Model-level tests for the auth tables."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.core import HouseholdInvite, Session


def test_session_roundtrip(db):
    s = Session(
        user_id=DEV_USER_ID,
        token_hash="a" * 64,
        active_household_id=DEV_HOUSEHOLD_ID,
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    db.add(s)
    db.flush()
    fetched = db.get(Session, s.id)
    assert fetched is not None
    assert fetched.token_hash == "a" * 64
    assert fetched.revoked_at is None
    assert fetched.metadata_ == {}


def test_household_invite_roundtrip(db):
    inv = HouseholdInvite(
        household_id=DEV_HOUSEHOLD_ID,
        token_hash="b" * 64,
        role="member",
        created_by_user_id=DEV_USER_ID,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(inv)
    db.flush()
    fetched = db.get(HouseholdInvite, inv.id)
    assert fetched is not None
    assert fetched.role == "member"
    assert fetched.accepted_at is None
    assert fetched.revoked_at is None
```

- [ ] **Step 6: Run the test**

Run: `uv run pytest tests/test_auth_models.py -v`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/app/models/core.py \
  apps/backend/alembic/versions/0004_real_auth.py \
  apps/backend/tests/test_auth_models.py
git commit -m "feat(auth): add Session, HouseholdInvite models and user auth columns (migration 0004)"
```

---

### Task 3: Password hashing helpers (passlib + bcrypt)

**Files:**
- Create: `apps/backend/app/services/auth/__init__.py`
- Create: `apps/backend/app/services/auth/passwords.py`
- Test: `apps/backend/tests/test_auth_passwords.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_auth_passwords.py`:

```python
"""Tests for the password hashing helpers."""
from __future__ import annotations

from app.services.auth.passwords import hash_password, verify_password


def test_hash_and_verify_password():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert hashed.startswith("$2")  # bcrypt prefix
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_each_hash_is_unique_even_for_same_password():
    a = hash_password("hunter2")
    b = hash_password("hunter2")
    assert a != b  # bcrypt salts each call
    assert verify_password("hunter2", a)
    assert verify_password("hunter2", b)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_auth_passwords.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.auth'`.

- [ ] **Step 3: Create the package marker**

Create `apps/backend/app/services/auth/__init__.py`:

```python
"""Authentication helpers — password hashing, session tokens, throttling."""
```

- [ ] **Step 4: Create the password helper**

Create `apps/backend/app/services/auth/passwords.py`:

```python
"""Password hashing and verification via passlib's bcrypt backend."""
from __future__ import annotations

from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of the plaintext password."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True iff `plain` matches the stored bcrypt hash."""
    return _pwd_context.verify(plain, hashed)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_auth_passwords.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/services/auth/ apps/backend/tests/test_auth_passwords.py
git commit -m "feat(auth): add bcrypt password hashing helpers"
```

---

### Task 4: Session token + cookie helpers

**Files:**
- Create: `apps/backend/app/services/auth/sessions.py`
- Test: `apps/backend/tests/test_auth_sessions.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_auth_sessions.py`:

```python
"""Tests for session token generation and lifecycle."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.auth import DEV_HOUSEHOLD_ID, DEV_USER_ID
from app.models.core import Session, User
from app.services.auth import sessions as session_svc


def test_generate_token_returns_raw_and_hash():
    raw, hashed = session_svc.generate_session_token()
    assert raw and hashed
    assert raw != hashed
    assert len(hashed) == 64  # sha256 hex
    assert session_svc.hash_session_token(raw) == hashed


def test_create_and_lookup_session(db):
    user = db.get(User, DEV_USER_ID)
    sess, raw = session_svc.create_session(
        db, user=user, active_household_id=DEV_HOUSEHOLD_ID,
        user_agent="pytest", ip="127.0.0.1",
    )
    assert sess.id is not None
    assert sess.token_hash == session_svc.hash_session_token(raw)
    assert sess.expires_at > datetime.now(UTC)
    assert sess.revoked_at is None
    assert sess.metadata_ == {"user_agent": "pytest", "ip": "127.0.0.1"}

    fetched = session_svc.get_session_by_raw_token(db, raw)
    assert fetched is not None
    assert fetched.id == sess.id
    assert fetched.last_used_at is not None


def test_revoked_session_is_not_returned(db):
    user = db.get(User, DEV_USER_ID)
    sess, raw = session_svc.create_session(
        db, user=user, active_household_id=DEV_HOUSEHOLD_ID,
    )
    session_svc.revoke_session(db, sess)
    assert session_svc.get_session_by_raw_token(db, raw) is None


def test_expired_session_is_not_returned(db):
    user = db.get(User, DEV_USER_ID)
    sess, raw = session_svc.create_session(
        db, user=user, active_household_id=DEV_HOUSEHOLD_ID,
    )
    sess.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.flush()
    assert session_svc.get_session_by_raw_token(db, raw) is None


def test_unknown_token_returns_none(db):
    assert session_svc.get_session_by_raw_token(db, "no-such-token") is None


def test_revoke_other_sessions(db):
    user = db.get(User, DEV_USER_ID)
    s1, _ = session_svc.create_session(db, user=user, active_household_id=DEV_HOUSEHOLD_ID)
    s2, _ = session_svc.create_session(db, user=user, active_household_id=DEV_HOUSEHOLD_ID)
    s3, _ = session_svc.create_session(db, user=user, active_household_id=DEV_HOUSEHOLD_ID)
    session_svc.revoke_other_sessions(db, user=user, except_session=s2)
    db.refresh(s1)
    db.refresh(s2)
    db.refresh(s3)
    assert s1.revoked_at is not None
    assert s2.revoked_at is None
    assert s3.revoked_at is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_auth_sessions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.auth.sessions'`.

- [ ] **Step 3: Create the session helper module**

Create `apps/backend/app/services/auth/sessions.py`:

```python
"""Session token generation, lookup, lifecycle, and cookie helpers.

Tokens: `secrets.token_urlsafe(32)` generates a 43-char URL-safe random string.
Only the SHA-256 hash is stored; the raw token lives in the cookie. A DB leak
therefore cannot yield live sessions.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Response
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.models.core import Session, User


def generate_session_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hash). The raw token goes in the cookie."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_session_token(raw)


def hash_session_token(raw: str) -> str:
    """SHA-256 hex digest of a raw session token."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_session(
    db: DbSession,
    *,
    user: User,
    active_household_id=None,
    user_agent: str | None = None,
    ip: str | None = None,
) -> tuple[Session, str]:
    """Create a session row; return (session, raw_token)."""
    raw, hashed = generate_session_token()
    now = datetime.now(UTC)
    meta: dict = {}
    if user_agent:
        meta["user_agent"] = user_agent
    if ip:
        meta["ip"] = ip
    sess = Session(
        user_id=user.id,
        token_hash=hashed,
        active_household_id=active_household_id,
        expires_at=now + timedelta(days=settings.session_max_age_days),
        last_used_at=now,
        metadata_=meta,
    )
    db.add(sess)
    db.flush()
    return sess, raw


def get_session_by_raw_token(db: DbSession, raw_token: str) -> Session | None:
    """Look up a valid session by its raw cookie token. Updates last_used_at on hit."""
    if not raw_token:
        return None
    hashed = hash_session_token(raw_token)
    sess = db.query(Session).filter(Session.token_hash == hashed).one_or_none()
    if sess is None:
        return None
    if sess.revoked_at is not None:
        return None
    if sess.expires_at <= datetime.now(UTC):
        return None
    sess.last_used_at = datetime.now(UTC)
    db.flush()
    return sess


def revoke_session(db: DbSession, sess: Session) -> None:
    """Mark a session revoked. Idempotent."""
    if sess.revoked_at is None:
        sess.revoked_at = datetime.now(UTC)
        db.flush()


def revoke_other_sessions(
    db: DbSession, *, user: User, except_session: Session | None = None
) -> int:
    """Revoke all of a user's non-revoked sessions except the given one. Returns count."""
    q = db.query(Session).filter(
        Session.user_id == user.id, Session.revoked_at.is_(None)
    )
    if except_session is not None:
        q = q.filter(Session.id != except_session.id)
    now = datetime.now(UTC)
    count = 0
    for s in q.all():
        s.revoked_at = now
        count += 1
    db.flush()
    return count


# ---------- Cookie helpers ----------


def set_session_cookie(response: Response, raw_token: str) -> None:
    """Attach the session cookie to a response."""
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        max_age=settings.session_max_age_days * 24 * 3600,
        httponly=True,
        samesite=settings.session_cookie_samesite,
        secure=settings.session_cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Remove the session cookie from the client."""
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_auth_sessions.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/services/auth/sessions.py apps/backend/tests/test_auth_sessions.py
git commit -m "feat(auth): add session token, lifecycle, and cookie helpers"
```

---

### Task 5: Conftest dependency override + `real_auth` marker (the safety net)

**Files:**
- Modify: `apps/backend/tests/conftest.py`
- Modify: `apps/backend/pyproject.toml` (register the pytest marker)

This task MUST land before Task 6 (the `auth.py` swap), because Task 6 makes the bare auth dependencies require a real session — which would 401 every existing test. The override installed here lets the 213 existing tests continue to pass during and after Task 6.

- [ ] **Step 1: Register the `real_auth` pytest marker**

In `apps/backend/pyproject.toml`, locate or add the `[tool.pytest.ini_options]` section. If it does not exist, append at the end of the file:

```toml
[tool.pytest.ini_options]
markers = [
    "real_auth: opt out of the conftest auth dependency override; exercise the real signup/login/session flow",
]
```

If the section already exists, add the `markers` entry alongside its existing keys (keeping any existing markers).

- [ ] **Step 2: Rewrite `conftest.py` with the dependency override**

Replace the entire contents of `apps/backend/tests/conftest.py` with:

```python
"""
Shared pytest fixtures.

Tests run against the real local Postgres (per CLAUDE.md: do NOT use SQLite —
we rely on JSONB and array types). Each test runs inside a transaction that's
rolled back at teardown, so tests don't leak rows.

Auth strategy: the dev user/household are seeded here (not at app startup) using
stable IDs from `app.auth` (DEV_USER_ID, DEV_HOUSEHOLD_ID). An autouse fixture
installs `app.dependency_overrides` for `get_current_user`/`get_current_household`
so every test resolves to the seeded fixture user/household, exactly as before.
Tests marked `@pytest.mark.real_auth` opt out of the override and exercise the
real signup/login/session flow.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.auth import (
    DEV_HOUSEHOLD_ID,
    DEV_USER_EMAIL,
    DEV_USER_ID,
    get_current_household,
    get_current_user,
    seed_reference_data,
)
from app.db import SessionLocal, engine
from app.main import app
from app.models.ai import Briefing, Conversation
from app.models.community import CommunityItem
from app.models.content import ContentItem
from app.models.core import (
    Event,
    Household,
    HouseholdMember,
    Subscription,
    User,
)
from app.models.food import (
    FoodWasteEvent,
    MealPlan,
    PantryItem,
    PreservationJob,
    Recipe,
    ShoppingList,
)


def _seed_test_user_and_household() -> None:
    """Seed the test User + Household + HouseholdMember + Subscription with stable IDs.

    This is the old `seed_dev_fixtures` logic, relocated from app startup. The
    IDs match the constants ~30 test files import from `app.auth`.
    """
    with SessionLocal() as db_:
        user = db_.get(User, DEV_USER_ID)
        if user is None:
            db_.add(User(id=DEV_USER_ID, email=DEV_USER_EMAIL, display_name="Test User"))
            db_.flush()

        household = db_.get(Household, DEV_HOUSEHOLD_ID)
        if household is None:
            db_.add(Household(id=DEV_HOUSEHOLD_ID, name="Test Household", size=2))
            db_.flush()

        membership = (
            db_.query(HouseholdMember)
            .filter_by(user_id=DEV_USER_ID, household_id=DEV_HOUSEHOLD_ID)
            .one_or_none()
        )
        if membership is None:
            db_.add(HouseholdMember(
                user_id=DEV_USER_ID, household_id=DEV_HOUSEHOLD_ID, role="owner"
            ))

        subscription = (
            db_.query(Subscription).filter_by(user_id=DEV_USER_ID).one_or_none()
        )
        if subscription is None:
            db_.add(Subscription(
                user_id=DEV_USER_ID, plan="suite", status="active",
                tier_a_enabled=True, tier_b_enabled=True,
            ))
        else:
            subscription.tier_b_enabled = True

        db_.commit()


@pytest.fixture(scope="session", autouse=True)
def _seed_session_fixtures():
    """Seed reference data (ingredients, badges) and the test user/household once per session."""
    _seed_test_user_and_household()
    with SessionLocal() as db_:
        seed_reference_data(db_)
        db_.commit()


def _override_get_current_user():
    with SessionLocal() as db_:
        return db_.get(User, DEV_USER_ID)


def _override_get_current_household():
    with SessionLocal() as db_:
        return db_.get(Household, DEV_HOUSEHOLD_ID)


@pytest.fixture(autouse=True)
def _auth_override(request):
    """Install dependency overrides for tests that act as the seeded fixture.

    Tests marked `@pytest.mark.real_auth` opt out — those tests exercise the
    real signup/login/session flow with no override.
    """
    if request.node.get_closest_marker("real_auth"):
        yield
        return
    app.dependency_overrides[get_current_user] = _override_get_current_user
    app.dependency_overrides[get_current_household] = _override_get_current_household
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_household, None)


@pytest.fixture(autouse=True)
def _clean_household_data():
    """Wipe per-household state before each test so endpoint tests (which commit)
    don't bleed into subsequent tests. The dev household + ingredient catalog
    are preserved."""
    with SessionLocal() as db_:
        # Order matters for FKs: child tables before parents.
        db_.query(FoodWasteEvent).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        db_.query(PreservationJob).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        db_.query(ShoppingList).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        db_.query(MealPlan).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        db_.query(PantryItem).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        db_.query(CommunityItem).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        # Recipes are not scoped by household, but we wipe ai-generated ones
        # because tests create them freely. User-created recipes (if any) stay.
        db_.query(Recipe).filter_by(is_ai_generated=True).delete()
        db_.query(Briefing).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        # Content items are global (no household_id); tests create them freely.
        db_.query(ContentItem).delete()
        db_.query(Conversation).filter_by(household_id=DEV_HOUSEHOLD_ID).delete()
        # Events are wiped wholesale: some (e.g. content enrichment) have no
        # household_id, and no test depends on pre-existing event rows.
        db_.query(Event).delete()
        db_.commit()
    yield


@pytest.fixture
def db() -> Session:
    """A SQLAlchemy session bound to a transaction that rolls back at teardown."""
    connection = engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
```

Note: this conftest imports `seed_reference_data` from `app.auth` — that function will be created in Task 6. Until Task 6 lands, `seed_dev_fixtures` still exists and seeds everything; the import will fail. Therefore **do not run pytest between Steps 2 and Task 6**; commit this task and proceed directly to Task 6 in the same working session.

- [ ] **Step 3: Commit (do not run the test suite between this and Task 6)**

```bash
git add apps/backend/tests/conftest.py apps/backend/pyproject.toml
git commit -m "test(auth): install dependency override + real_auth marker (safety net for the auth.py swap)"
```

---

### Task 6: `auth.py` swap + main.py lifespan swap

**Files:**
- Modify: `apps/backend/app/auth.py`
- Modify: `apps/backend/app/main.py`

After this task the 213 existing tests must still pass — Task 5's override is exactly what holds them up.

- [ ] **Step 1: Rewrite `app/auth.py`**

Replace the entire contents of `apps/backend/app/auth.py` with:

```python
"""
Auth dependencies for FastAPI.

The two dependencies below are the single seam between the rest of the app and
the auth implementation. `CurrentUser` / `CurrentHousehold` keep their names
and types, so every existing router and service is untouched.

A valid session is required: the `hearth_session` cookie must hash to a row in
`core.sessions` that is not revoked and not expired. `get_current_household`
resolves to the session's `active_household_id`, falling back to (and persisting)
the user's first membership.

DEV_USER_ID / DEV_HOUSEHOLD_ID remain as constants — the test harness
(tests/conftest.py) seeds rows with these stable IDs and installs
`app.dependency_overrides` so every existing test acts as that fixture.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.db import SessionLocal, get_db
from app.models.core import Household, HouseholdMember, User
from app.services.auth.sessions import get_session_by_raw_token
from app.services.ingredients import seed_starter_ingredients
from app.services.streaks import seed_badge_definitions

# Stable UUIDs for the test fixture user/household. They live here so the ~30
# test files that import `from app.auth import DEV_USER_ID, DEV_HOUSEHOLD_ID`
# keep working unchanged. The rows themselves are seeded by tests/conftest.py.
DEV_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEV_HOUSEHOLD_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
DEV_USER_EMAIL = "dev@frugal-living.local"


def seed_reference_data(db: DbSession) -> None:
    """Seed global, not-user-specific reference data on app startup.

    Replaces the old `seed_dev_fixtures` — the dev user/household auto-seed is
    gone; new users sign up through the UI.
    """
    seed_starter_ingredients(db)
    seed_badge_definitions(db)


def get_current_user(
    db: Annotated[DbSession, Depends(get_db)],
    session_token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> User:
    """Resolve the logged-in user from the session cookie. 401 if no valid session."""
    if not session_token:
        raise HTTPException(status_code=401, detail="not authenticated")
    sess = get_session_by_raw_token(db, session_token)
    if sess is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


def get_current_household(
    db: Annotated[DbSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    session_token: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> Household:
    """Resolve the active household for the current session.

    Falls back to the user's first HouseholdMember and persists it on the
    session as the active household.
    """
    # Look up the session again (already validated by get_current_user).
    sess = get_session_by_raw_token(db, session_token) if session_token else None
    if sess is None:
        raise HTTPException(status_code=401, detail="not authenticated")

    if sess.active_household_id is not None:
        household = db.get(Household, sess.active_household_id)
        if household is not None:
            return household

    membership = (
        db.query(HouseholdMember)
        .filter(HouseholdMember.user_id == user.id)
        .order_by(HouseholdMember.created_at)
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=400, detail="user has no household")
    sess.active_household_id = membership.household_id
    db.flush()
    household = db.get(Household, membership.household_id)
    assert household is not None
    return household


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentHousehold = Annotated[Household, Depends(get_current_household)]
```

- [ ] **Step 2: Update `main.py` lifespan**

In `apps/backend/app/main.py`, replace this block:

```python
from app.auth import seed_dev_fixtures


@asynccontextmanager
async def lifespan(_app: FastAPI):
    seed_dev_fixtures()
    yield
```

with:

```python
from app.auth import seed_reference_data
from app.db import SessionLocal


@asynccontextmanager
async def lifespan(_app: FastAPI):
    with SessionLocal() as db:
        seed_reference_data(db)
        db.commit()
    yield
```

- [ ] **Step 3: Run the full backend suite — the safety net moment**

Run: `uv run pytest -q`
Expected: **214 passed, 1 skipped** (the prior 213 + 6 from Task 4 + 2 from Task 2 = ~221; actual: the prior 213 from before Task 2 + 2 model + 2 password + 6 sessions = 223; minor variance — what matters is **zero failures and zero new errors**). If any food/Tier B test fails, the override is wrong — fix conftest, do not proceed.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/app/auth.py apps/backend/app/main.py
git commit -m "feat(auth): swap auth.py dependencies to session cookie + split reference-data seed"
```

---

### Task 7: Auth schemas + signup endpoint + router mount

**Files:**
- Create: `apps/backend/app/schemas/auth.py`
- Create: `apps/backend/app/routers/auth.py`
- Modify: `apps/backend/app/main.py`
- Test: `apps/backend/tests/test_auth_signup.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_auth_signup.py`:

```python
"""Tests for POST /auth/signup."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models.core import HouseholdMember, Subscription, User

pytestmark = pytest.mark.real_auth


@pytest.fixture
def client():
    return TestClient(app)


def test_signup_creates_user_household_membership_subscription_and_session(client):
    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "alice@example.com",
            "password": "hunter2hunter2",
            "display_name": "Alice",
            "household_name": "Alice's Place",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["email"] == "alice@example.com"
    assert body["household"]["name"] == "Alice's Place"
    # Cookie was set
    assert settings.session_cookie_name in resp.cookies

    with SessionLocal() as db:
        user = db.query(User).filter_by(email="alice@example.com").one()
        assert user.hashed_password is not None
        membership = db.query(HouseholdMember).filter_by(user_id=user.id).one()
        assert membership.role == "owner"
        sub = db.query(Subscription).filter_by(user_id=user.id).one()
        assert sub.tier_a_enabled is True
        assert sub.tier_b_enabled is True
        assert sub.tier_s_enabled is False
        db.delete(membership)
        db.delete(sub)
        db.delete(db.query(__import__("app.models.core", fromlist=["Household"]).Household)
                  .filter_by(id=membership.household_id).one())
        db.delete(user)
        db.commit()


def test_signup_rejects_short_password(client):
    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "bob@example.com", "password": "short",
            "display_name": "Bob", "household_name": "Bob",
        },
    )
    assert resp.status_code == 422


def test_signup_rejects_duplicate_email(client):
    first = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "carol@example.com", "password": "hunter2hunter2",
            "display_name": "Carol", "household_name": "Carol",
        },
    )
    assert first.status_code == 200
    dup = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "carol@example.com", "password": "different-password",
            "display_name": "Carol2", "household_name": "Carol2",
        },
    )
    assert dup.status_code == 409
    # Cleanup
    with SessionLocal() as db:
        u = db.query(User).filter_by(email="carol@example.com").one()
        membership = db.query(HouseholdMember).filter_by(user_id=u.id).one()
        sub = db.query(Subscription).filter_by(user_id=u.id).one()
        from app.models.core import Household as H
        h = db.get(H, membership.household_id)
        db.delete(sub); db.delete(membership)
        if h: db.delete(h)
        db.delete(u)
        db.commit()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_auth_signup.py -v`
Expected: FAIL (the auth router is not mounted yet — 404s).

- [ ] **Step 3: Create the schemas**

Create `apps/backend/app/schemas/auth.py`:

```python
"""Auth-tier request/response schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=200)
    display_name: str = Field(..., min_length=1, max_length=120)
    household_name: str = Field(..., min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=200)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=200)
    new_password: str = Field(..., min_length=8, max_length=200)


class CreateHouseholdRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class SwitchHouseholdRequest(BaseModel):
    household_id: uuid.UUID


class CreateInviteRequest(BaseModel):
    role: str = Field(default="member", pattern=r"^(member|viewer)$")
    email: str | None = Field(default=None, max_length=320)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    display_name: str | None


class HouseholdRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str


class MembershipRead(BaseModel):
    household: HouseholdRead
    role: str


class MeResponse(BaseModel):
    user: UserRead
    memberships: list[MembershipRead]
    active_household: HouseholdRead | None


class SignupResponse(BaseModel):
    user: UserRead
    household: HouseholdRead


class LoginResponse(BaseModel):
    user: UserRead
    active_household: HouseholdRead


class InvitePreview(BaseModel):
    household_name: str
    role: str
    inviter_name: str | None
    expires_at: datetime


class CreateInviteResponse(BaseModel):
    token: str  # raw token (one-time return)
    url: str    # /invite/<token>
    expires_at: datetime
```

- [ ] **Step 4: Create the auth router with the signup endpoint**

Create `apps/backend/app/routers/auth.py`:

```python
"""Auth endpoints: signup, login, logout, me, password, multi-household, invites."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.core import (
    AuditLog,
    Household,
    HouseholdMember,
    Subscription,
    User,
)
from app.schemas.auth import (
    HouseholdRead,
    SignupRequest,
    SignupResponse,
    UserRead,
)
from app.services.auth import sessions as session_svc
from app.services.auth.passwords import hash_password

router = APIRouter()


def _request_meta(request: Request) -> tuple[str | None, str | None]:
    ua = request.headers.get("user-agent")
    ip = request.client.host if request.client else None
    return ua, ip


def _audit(db: Session, *, action: str, user_id, payload: dict | None = None) -> None:
    db.add(AuditLog(
        actor_user_id=user_id,
        action=action,
        target_type="user",
        target_id=user_id,
        payload=payload or {},
    ))


@router.post("/signup", response_model=SignupResponse)
def signup(
    request: SignupRequest,
    response: Response,
    http_request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> SignupResponse:
    """Create a new user + household + owner membership + free subscription; open a session."""
    user = User(
        email=str(request.email).lower(),
        hashed_password=hash_password(request.password),
        display_name=request.display_name,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="email already in use") from None

    household = Household(name=request.household_name)
    db.add(household)
    db.flush()

    db.add(HouseholdMember(user_id=user.id, household_id=household.id, role="owner"))
    db.add(Subscription(
        user_id=user.id, plan="free", status="active",
        tier_a_enabled=True, tier_b_enabled=True, tier_s_enabled=False,
    ))
    db.flush()

    ua, ip = _request_meta(http_request)
    sess, raw_token = session_svc.create_session(
        db, user=user, active_household_id=household.id, user_agent=ua, ip=ip,
    )
    _audit(db, action="auth.signup", user_id=user.id, payload={"email": user.email})
    db.commit()

    session_svc.set_session_cookie(response, raw_token)
    return SignupResponse(
        user=UserRead.model_validate(user),
        household=HouseholdRead.model_validate(household),
    )
```

- [ ] **Step 5: Mount the auth router in `main.py`**

In `apps/backend/app/main.py`, change the import line:

```python
from app.routers import ai, community, content, food, health, tracking
```

to:

```python
from app.routers import ai, auth, community, content, food, health, tracking
```

Then add this line immediately after the existing `app.include_router(tracking.router, ...)` line, before the `# Tier B — community` comment:

```python
# Auth (core)
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
```

- [ ] **Step 6: Run the signup tests**

Run: `uv run pytest tests/test_auth_signup.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add apps/backend/app/schemas/auth.py apps/backend/app/routers/auth.py \
  apps/backend/app/main.py apps/backend/tests/test_auth_signup.py
git commit -m "feat(auth): add signup endpoint, schemas, and mount /api/v1/auth"
```

---

### Task 8: Login endpoint + per-email throttling

**Files:**
- Create: `apps/backend/app/services/auth/throttle.py`
- Modify: `apps/backend/app/routers/auth.py`
- Test: `apps/backend/tests/test_auth_login.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_auth_login.py`:

```python
"""Tests for POST /auth/login (and login throttling)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models.core import Household, HouseholdMember, Subscription, User

pytestmark = pytest.mark.real_auth


@pytest.fixture
def client():
    return TestClient(app)


def _signup(client, email="dana@example.com", password="hunter2hunter2"):
    return client.post("/api/v1/auth/signup", json={
        "email": email, "password": password,
        "display_name": "Dana", "household_name": "Dana",
    })


def _cleanup(email):
    with SessionLocal() as db:
        u = db.query(User).filter_by(email=email).one_or_none()
        if not u: return
        membership = db.query(HouseholdMember).filter_by(user_id=u.id).one_or_none()
        sub = db.query(Subscription).filter_by(user_id=u.id).one_or_none()
        from app.models.core import Session as S
        for s in db.query(S).filter_by(user_id=u.id).all():
            db.delete(s)
        if sub: db.delete(sub)
        if membership:
            h = db.get(Household, membership.household_id)
            db.delete(membership)
            if h: db.delete(h)
        db.delete(u)
        db.commit()


def test_login_with_correct_credentials_sets_session_cookie(client):
    _signup(client)
    try:
        # Use a fresh client (no cookie carried from signup).
        c2 = TestClient(app)
        resp = c2.post("/api/v1/auth/login", json={
            "email": "dana@example.com", "password": "hunter2hunter2",
        })
        assert resp.status_code == 200, resp.text
        assert settings.session_cookie_name in resp.cookies
    finally:
        _cleanup("dana@example.com")


def test_login_with_wrong_password_returns_401(client):
    _signup(client)
    try:
        c2 = TestClient(app)
        resp = c2.post("/api/v1/auth/login", json={
            "email": "dana@example.com", "password": "wrong",
        })
        assert resp.status_code == 401
    finally:
        _cleanup("dana@example.com")


def test_login_with_unknown_email_returns_401(client):
    c2 = TestClient(app)
    resp = c2.post("/api/v1/auth/login", json={
        "email": "nobody@example.com", "password": "whatever",
    })
    assert resp.status_code == 401


def test_login_locks_after_threshold_failures(client):
    _signup(client)
    try:
        c2 = TestClient(app)
        # Default threshold is 5
        for _ in range(settings.login_lockout_threshold):
            c2.post("/api/v1/auth/login", json={
                "email": "dana@example.com", "password": "wrong",
            })
        # Even with correct password, locked
        resp = c2.post("/api/v1/auth/login", json={
            "email": "dana@example.com", "password": "hunter2hunter2",
        })
        assert resp.status_code == 429
    finally:
        _cleanup("dana@example.com")


def test_successful_login_resets_failed_count(client):
    _signup(client)
    try:
        c2 = TestClient(app)
        c2.post("/api/v1/auth/login", json={
            "email": "dana@example.com", "password": "wrong",
        })
        c2.post("/api/v1/auth/login", json={
            "email": "dana@example.com", "password": "wrong",
        })
        resp = c2.post("/api/v1/auth/login", json={
            "email": "dana@example.com", "password": "hunter2hunter2",
        })
        assert resp.status_code == 200
        with SessionLocal() as db:
            u = db.query(User).filter_by(email="dana@example.com").one()
            assert u.failed_login_count == 0
            assert u.locked_until is None
    finally:
        _cleanup("dana@example.com")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_auth_login.py -v`
Expected: FAIL (login endpoint not implemented).

- [ ] **Step 3: Create the throttle helper**

Create `apps/backend/app/services/auth/throttle.py`:

```python
"""Per-email login throttling. Updates failed_login_count / locked_until on User."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.models.core import User


def is_locked(user: User) -> tuple[bool, datetime | None]:
    """True if the user's account is currently in lockout."""
    if user.locked_until and user.locked_until > datetime.now(UTC):
        return True, user.locked_until
    return False, None


def register_failed_login(db: Session, user: User) -> None:
    """Increment the failure counter; engage lockout at the threshold."""
    user.failed_login_count += 1
    if user.failed_login_count >= settings.login_lockout_threshold:
        user.locked_until = datetime.now(UTC) + timedelta(
            minutes=settings.login_lockout_minutes
        )
    db.flush()


def reset_throttle(db: Session, user: User) -> None:
    """Clear failed-login state after a successful login."""
    user.failed_login_count = 0
    user.locked_until = None
    db.flush()
```

- [ ] **Step 4: Add the login endpoint to the auth router**

In `apps/backend/app/routers/auth.py`, add these imports at the top alongside the existing imports:

```python
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    HouseholdRead,
    SignupRequest,
    SignupResponse,
    UserRead,
)
from app.services.auth import throttle as throttle_svc
from app.services.auth.passwords import verify_password
```

(Replace the existing `from app.schemas.auth import ...` block with the consolidated one above.)

Then append this endpoint to the bottom of `apps/backend/app/routers/auth.py`:

```python
@router.post("/login", response_model=LoginResponse)
def login(
    request: LoginRequest,
    response: Response,
    http_request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> LoginResponse:
    """Verify credentials, open a session, set the cookie. 401 / 429 on failure."""
    user = db.query(User).filter(User.email == str(request.email).lower()).one_or_none()
    if user is None:
        # Same status as wrong-password to avoid email enumeration.
        raise HTTPException(status_code=401, detail="invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="invalid email or password")

    locked, until = throttle_svc.is_locked(user)
    if locked:
        raise HTTPException(
            status_code=429,
            detail=f"account locked until {until.isoformat()}",
        )

    if user.hashed_password is None or not verify_password(
        request.password, user.hashed_password
    ):
        throttle_svc.register_failed_login(db, user)
        db.commit()
        raise HTTPException(status_code=401, detail="invalid email or password")

    throttle_svc.reset_throttle(db, user)

    # Default the new session's active household to the user's first membership.
    membership = (
        db.query(HouseholdMember)
        .filter(HouseholdMember.user_id == user.id)
        .order_by(HouseholdMember.created_at)
        .first()
    )
    active_household_id = membership.household_id if membership else None

    ua, ip = _request_meta(http_request)
    sess, raw_token = session_svc.create_session(
        db, user=user, active_household_id=active_household_id, user_agent=ua, ip=ip,
    )
    _audit(db, action="auth.login", user_id=user.id, payload={"email": user.email})
    db.commit()

    session_svc.set_session_cookie(response, raw_token)
    household = db.get(Household, active_household_id) if active_household_id else None
    if household is None:
        raise HTTPException(status_code=400, detail="user has no household")
    return LoginResponse(
        user=UserRead.model_validate(user),
        active_household=HouseholdRead.model_validate(household),
    )
```

- [ ] **Step 5: Run the login tests**

Run: `uv run pytest tests/test_auth_login.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/services/auth/throttle.py \
  apps/backend/app/routers/auth.py apps/backend/tests/test_auth_login.py
git commit -m "feat(auth): add login endpoint with per-email throttling and lockout"
```

---

### Task 9: Logout + `GET /me`

**Files:**
- Modify: `apps/backend/app/routers/auth.py`
- Test: `apps/backend/tests/test_auth_logout_me.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_auth_logout_me.py`:

```python
"""Tests for POST /auth/logout and GET /auth/me."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models.core import (
    Household, HouseholdMember, Subscription, User,
)
from app.models.core import Session as DbSession

pytestmark = pytest.mark.real_auth


def _cleanup(email):
    with SessionLocal() as db:
        u = db.query(User).filter_by(email=email).one_or_none()
        if not u: return
        for s in db.query(DbSession).filter_by(user_id=u.id).all():
            db.delete(s)
        membership = db.query(HouseholdMember).filter_by(user_id=u.id).one_or_none()
        sub = db.query(Subscription).filter_by(user_id=u.id).one_or_none()
        if sub: db.delete(sub)
        if membership:
            h = db.get(Household, membership.household_id)
            db.delete(membership)
            if h: db.delete(h)
        db.delete(u)
        db.commit()


def _signup_and_client():
    c = TestClient(app)
    c.post("/api/v1/auth/signup", json={
        "email": "ed@example.com", "password": "hunter2hunter2",
        "display_name": "Ed", "household_name": "Ed",
    })
    return c


def test_me_returns_user_memberships_and_active_household():
    c = _signup_and_client()
    try:
        resp = c.get("/api/v1/auth/me")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["user"]["email"] == "ed@example.com"
        assert len(body["memberships"]) == 1
        assert body["memberships"][0]["role"] == "owner"
        assert body["active_household"]["name"] == "Ed"
    finally:
        _cleanup("ed@example.com")


def test_me_without_cookie_returns_401():
    c = TestClient(app)
    resp = c.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_logout_revokes_session_and_clears_cookie():
    c = _signup_and_client()
    try:
        with SessionLocal() as db:
            u = db.query(User).filter_by(email="ed@example.com").one()
            assert db.query(DbSession).filter_by(user_id=u.id, revoked_at=None).count() == 1

        resp = c.post("/api/v1/auth/logout")
        assert resp.status_code == 200
        # Cookie deleted (Set-Cookie with Max-Age=0 / expires in the past)
        cookie_header = resp.headers.get("set-cookie", "")
        assert settings.session_cookie_name in cookie_header

        with SessionLocal() as db:
            u = db.query(User).filter_by(email="ed@example.com").one()
            assert db.query(DbSession).filter_by(user_id=u.id, revoked_at=None).count() == 0

        # The same client can no longer access /me.
        me = c.get("/api/v1/auth/me")
        assert me.status_code == 401
    finally:
        _cleanup("ed@example.com")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_auth_logout_me.py -v`
Expected: FAIL.

- [ ] **Step 3: Add `MeResponse`/`MembershipRead` imports + endpoints**

In `apps/backend/app/routers/auth.py`, update the schemas import block to include the new names:

```python
from app.schemas.auth import (
    HouseholdRead,
    LoginRequest,
    LoginResponse,
    MeResponse,
    MembershipRead,
    SignupRequest,
    SignupResponse,
    UserRead,
)
```

Also add this import at the top (alongside the existing `from app.auth import CurrentUser, CurrentHousehold` — which you'll add now if not present):

```python
from app.auth import CurrentHousehold, CurrentUser
from app.services.auth.sessions import (
    clear_session_cookie,
    get_session_by_raw_token,
    revoke_session,
    set_session_cookie,
)
```

(Replace any earlier narrower `from app.services.auth.sessions import ...` line with this consolidated one.)

Also add `Cookie` to the FastAPI import line:

```python
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
```

And add this import:

```python
from app.config import settings
```

Then append these two endpoints to the bottom of `apps/backend/app/routers/auth.py`:

```python
@router.post("/logout")
def logout(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
    session_token: Annotated[
        str | None, Cookie(alias=settings.session_cookie_name)
    ] = None,
) -> dict:
    """Revoke the current session and clear the cookie."""
    if session_token:
        sess = get_session_by_raw_token(db, session_token)
        if sess is not None:
            revoke_session(db, sess)
    _audit(db, action="auth.logout", user_id=user.id)
    db.commit()
    clear_session_cookie(response)
    return {"status": "logged_out"}


@router.get("/me", response_model=MeResponse)
def me(
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
    household: CurrentHousehold,
) -> MeResponse:
    """Return the current user, their household memberships, and the active household."""
    memberships = (
        db.query(HouseholdMember)
        .filter(HouseholdMember.user_id == user.id)
        .all()
    )
    member_reads = []
    for m in memberships:
        h = db.get(Household, m.household_id)
        if h is None:
            continue
        member_reads.append(MembershipRead(
            household=HouseholdRead.model_validate(h),
            role=m.role,
        ))
    return MeResponse(
        user=UserRead.model_validate(user),
        memberships=member_reads,
        active_household=HouseholdRead.model_validate(household),
    )
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_auth_logout_me.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/routers/auth.py apps/backend/tests/test_auth_logout_me.py
git commit -m "feat(auth): add logout and GET /me endpoints"
```

---

### Task 10: Password change (+ revoke other sessions)

**Files:**
- Modify: `apps/backend/app/routers/auth.py`
- Test: `apps/backend/tests/test_auth_password.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_auth_password.py`:

```python
"""Tests for POST /auth/password."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models.core import (
    Household, HouseholdMember, Subscription, User,
)
from app.models.core import Session as DbSession

pytestmark = pytest.mark.real_auth


def _cleanup(email):
    with SessionLocal() as db:
        u = db.query(User).filter_by(email=email).one_or_none()
        if not u: return
        for s in db.query(DbSession).filter_by(user_id=u.id).all():
            db.delete(s)
        membership = db.query(HouseholdMember).filter_by(user_id=u.id).one_or_none()
        sub = db.query(Subscription).filter_by(user_id=u.id).one_or_none()
        if sub: db.delete(sub)
        if membership:
            h = db.get(Household, membership.household_id)
            db.delete(membership)
            if h: db.delete(h)
        db.delete(u)
        db.commit()


def test_password_change_requires_correct_current_password():
    c = TestClient(app)
    c.post("/api/v1/auth/signup", json={
        "email": "frank@example.com", "password": "hunter2hunter2",
        "display_name": "Frank", "household_name": "Frank",
    })
    try:
        bad = c.post("/api/v1/auth/password", json={
            "current_password": "wrong", "new_password": "new-password-123",
        })
        assert bad.status_code == 401
        ok = c.post("/api/v1/auth/password", json={
            "current_password": "hunter2hunter2", "new_password": "new-password-123",
        })
        assert ok.status_code == 200
        # Old password now fails on a new login
        c2 = TestClient(app)
        bad_login = c2.post("/api/v1/auth/login", json={
            "email": "frank@example.com", "password": "hunter2hunter2",
        })
        assert bad_login.status_code == 401
        good_login = c2.post("/api/v1/auth/login", json={
            "email": "frank@example.com", "password": "new-password-123",
        })
        assert good_login.status_code == 200
    finally:
        _cleanup("frank@example.com")


def test_password_change_revokes_other_sessions():
    c1 = TestClient(app)
    c1.post("/api/v1/auth/signup", json={
        "email": "gina@example.com", "password": "hunter2hunter2",
        "display_name": "Gina", "household_name": "Gina",
    })
    try:
        # Second device: log in to create another active session
        c2 = TestClient(app)
        c2.post("/api/v1/auth/login", json={
            "email": "gina@example.com", "password": "hunter2hunter2",
        })
        with SessionLocal() as db:
            u = db.query(User).filter_by(email="gina@example.com").one()
            assert db.query(DbSession).filter_by(user_id=u.id, revoked_at=None).count() == 2
        # Change password from c1 — c2's session should be revoked, c1's preserved
        c1.post("/api/v1/auth/password", json={
            "current_password": "hunter2hunter2", "new_password": "another-strong-pass",
        })
        with SessionLocal() as db:
            u = db.query(User).filter_by(email="gina@example.com").one()
            assert db.query(DbSession).filter_by(user_id=u.id, revoked_at=None).count() == 1
        # c1 still works, c2 is logged out
        assert c1.get("/api/v1/auth/me").status_code == 200
        assert c2.get("/api/v1/auth/me").status_code == 401
    finally:
        _cleanup("gina@example.com")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_auth_password.py -v`
Expected: FAIL.

- [ ] **Step 3: Add the endpoint**

In `apps/backend/app/routers/auth.py`, update the schemas import to include `PasswordChangeRequest`:

```python
from app.schemas.auth import (
    HouseholdRead,
    LoginRequest,
    LoginResponse,
    MeResponse,
    MembershipRead,
    PasswordChangeRequest,
    SignupRequest,
    SignupResponse,
    UserRead,
)
```

Add `hash_password` to the existing `passwords` import:

```python
from app.services.auth.passwords import hash_password, verify_password
```

Add `revoke_other_sessions` to the existing sessions import:

```python
from app.services.auth.sessions import (
    clear_session_cookie,
    create_session,
    get_session_by_raw_token,
    revoke_other_sessions,
    revoke_session,
    set_session_cookie,
)
```

(Wherever the router previously called `session_svc.create_session(...)`, you may either keep the module-prefixed form or use `create_session(...)` directly — pick one and be consistent. The tests don't care.)

Then append this endpoint:

```python
@router.post("/password")
def change_password(
    request: PasswordChangeRequest,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
    session_token: Annotated[
        str | None, Cookie(alias=settings.session_cookie_name)
    ] = None,
) -> dict:
    """Change password. Verifies the current one and revokes all *other* sessions."""
    if user.hashed_password is None or not verify_password(
        request.current_password, user.hashed_password
    ):
        raise HTTPException(status_code=401, detail="current password is wrong")
    user.hashed_password = hash_password(request.new_password)

    current_session = get_session_by_raw_token(db, session_token) if session_token else None
    revoke_other_sessions(db, user=user, except_session=current_session)
    _audit(db, action="auth.password_change", user_id=user.id)
    db.commit()
    return {"status": "password_changed"}
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_auth_password.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/routers/auth.py apps/backend/tests/test_auth_password.py
git commit -m "feat(auth): add password change endpoint (revokes other sessions)"
```

---

### Task 11: Create-household endpoint

**Files:**
- Modify: `apps/backend/app/routers/auth.py`
- Test: `apps/backend/tests/test_auth_create_household.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_auth_create_household.py`:

```python
"""Tests for POST /auth/households."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models.core import (
    Household, HouseholdMember, Subscription, User,
)
from app.models.core import Session as DbSession

pytestmark = pytest.mark.real_auth


def _cleanup(email):
    with SessionLocal() as db:
        u = db.query(User).filter_by(email=email).one_or_none()
        if not u: return
        for s in db.query(DbSession).filter_by(user_id=u.id).all():
            db.delete(s)
        memberships = db.query(HouseholdMember).filter_by(user_id=u.id).all()
        for m in memberships:
            h = db.get(Household, m.household_id)
            db.delete(m)
            if h: db.delete(h)
        sub = db.query(Subscription).filter_by(user_id=u.id).one_or_none()
        if sub: db.delete(sub)
        db.delete(u)
        db.commit()


def test_create_household_makes_caller_owner():
    c = TestClient(app)
    c.post("/api/v1/auth/signup", json={
        "email": "hank@example.com", "password": "hunter2hunter2",
        "display_name": "Hank", "household_name": "Primary",
    })
    try:
        resp = c.post("/api/v1/auth/households", json={"name": "Vacation Home"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "Vacation Home"
        # Caller is owner; total memberships now 2
        with SessionLocal() as db:
            u = db.query(User).filter_by(email="hank@example.com").one()
            memberships = db.query(HouseholdMember).filter_by(user_id=u.id).all()
            assert len(memberships) == 2
            assert all(m.role == "owner" for m in memberships)
    finally:
        _cleanup("hank@example.com")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_auth_create_household.py -v`
Expected: FAIL.

- [ ] **Step 3: Add the endpoint**

In `apps/backend/app/routers/auth.py`, update the schemas import to include `CreateHouseholdRequest`:

```python
from app.schemas.auth import (
    CreateHouseholdRequest,
    HouseholdRead,
    LoginRequest,
    LoginResponse,
    MeResponse,
    MembershipRead,
    PasswordChangeRequest,
    SignupRequest,
    SignupResponse,
    UserRead,
)
```

Then append:

```python
@router.post("/households", response_model=HouseholdRead)
def create_household(
    request: CreateHouseholdRequest,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> HouseholdRead:
    """Create a new household; the caller becomes its owner."""
    household = Household(name=request.name)
    db.add(household)
    db.flush()
    db.add(HouseholdMember(user_id=user.id, household_id=household.id, role="owner"))
    _audit(db, action="auth.household_created", user_id=user.id,
           payload={"household_id": str(household.id)})
    db.commit()
    db.refresh(household)
    return HouseholdRead.model_validate(household)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_auth_create_household.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/routers/auth.py apps/backend/tests/test_auth_create_household.py
git commit -m "feat(auth): add create-household endpoint"
```

---

### Task 12: Switch-household endpoint

**Files:**
- Modify: `apps/backend/app/routers/auth.py`
- Test: `apps/backend/tests/test_auth_switch_household.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_auth_switch_household.py`:

```python
"""Tests for POST /auth/switch-household."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models.core import (
    Household, HouseholdMember, Subscription, User,
)
from app.models.core import Session as DbSession

pytestmark = pytest.mark.real_auth


def _cleanup(email):
    with SessionLocal() as db:
        u = db.query(User).filter_by(email=email).one_or_none()
        if not u: return
        for s in db.query(DbSession).filter_by(user_id=u.id).all():
            db.delete(s)
        memberships = db.query(HouseholdMember).filter_by(user_id=u.id).all()
        for m in memberships:
            h = db.get(Household, m.household_id)
            db.delete(m)
            if h: db.delete(h)
        sub = db.query(Subscription).filter_by(user_id=u.id).one_or_none()
        if sub: db.delete(sub)
        db.delete(u)
        db.commit()


def test_switch_to_a_household_you_belong_to():
    c = TestClient(app)
    c.post("/api/v1/auth/signup", json={
        "email": "ivy@example.com", "password": "hunter2hunter2",
        "display_name": "Ivy", "household_name": "Primary",
    })
    try:
        new = c.post("/api/v1/auth/households", json={"name": "Cabin"}).json()
        resp = c.post("/api/v1/auth/switch-household", json={"household_id": new["id"]})
        assert resp.status_code == 200, resp.text
        me = c.get("/api/v1/auth/me").json()
        assert me["active_household"]["id"] == new["id"]
    finally:
        _cleanup("ivy@example.com")


def test_switch_to_unknown_household_returns_403():
    c = TestClient(app)
    c.post("/api/v1/auth/signup", json={
        "email": "jack@example.com", "password": "hunter2hunter2",
        "display_name": "Jack", "household_name": "Primary",
    })
    try:
        resp = c.post("/api/v1/auth/switch-household",
                      json={"household_id": str(uuid.uuid4())})
        assert resp.status_code == 403
    finally:
        _cleanup("jack@example.com")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_auth_switch_household.py -v`
Expected: FAIL.

- [ ] **Step 3: Add the endpoint**

In `apps/backend/app/routers/auth.py`, update the schemas import to include `SwitchHouseholdRequest`:

```python
from app.schemas.auth import (
    CreateHouseholdRequest,
    HouseholdRead,
    LoginRequest,
    LoginResponse,
    MeResponse,
    MembershipRead,
    PasswordChangeRequest,
    SignupRequest,
    SignupResponse,
    SwitchHouseholdRequest,
    UserRead,
)
```

Then append:

```python
@router.post("/switch-household", response_model=HouseholdRead)
def switch_household(
    request: SwitchHouseholdRequest,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
    session_token: Annotated[
        str | None, Cookie(alias=settings.session_cookie_name)
    ] = None,
) -> HouseholdRead:
    """Set the current session's active household. 403 if the user isn't a member."""
    membership = (
        db.query(HouseholdMember)
        .filter(
            HouseholdMember.user_id == user.id,
            HouseholdMember.household_id == request.household_id,
        )
        .one_or_none()
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="not a member of that household")

    sess = get_session_by_raw_token(db, session_token) if session_token else None
    if sess is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    sess.active_household_id = request.household_id
    db.flush()
    _audit(db, action="auth.household_switched", user_id=user.id,
           payload={"household_id": str(request.household_id)})
    db.commit()
    household = db.get(Household, request.household_id)
    assert household is not None
    return HouseholdRead.model_validate(household)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_auth_switch_household.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/app/routers/auth.py apps/backend/tests/test_auth_switch_household.py
git commit -m "feat(auth): add switch-household endpoint"
```

---

### Task 13: Household invites (service + 4 endpoints)

**Files:**
- Create: `apps/backend/app/services/auth/invites.py`
- Modify: `apps/backend/app/routers/auth.py`
- Test: `apps/backend/tests/test_auth_invites.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_auth_invites.py`:

```python
"""Tests for the household-invite endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models.core import (
    Household, HouseholdInvite, HouseholdMember, Subscription, User,
)
from app.models.core import Session as DbSession

pytestmark = pytest.mark.real_auth


def _cleanup(email):
    with SessionLocal() as db:
        u = db.query(User).filter_by(email=email).one_or_none()
        if not u: return
        for s in db.query(DbSession).filter_by(user_id=u.id).all():
            db.delete(s)
        for inv in db.query(HouseholdInvite).filter_by(created_by_user_id=u.id).all():
            db.delete(inv)
        memberships = db.query(HouseholdMember).filter_by(user_id=u.id).all()
        for m in memberships:
            h = db.get(Household, m.household_id)
            db.delete(m)
            if h:
                for inv in db.query(HouseholdInvite).filter_by(household_id=h.id).all():
                    db.delete(inv)
                # Also remove any other members of this household
                for om in db.query(HouseholdMember).filter_by(household_id=h.id).all():
                    db.delete(om)
                db.delete(h)
        sub = db.query(Subscription).filter_by(user_id=u.id).one_or_none()
        if sub: db.delete(sub)
        db.delete(u)
        db.commit()


def _signup(email, household="HH"):
    c = TestClient(app)
    c.post("/api/v1/auth/signup", json={
        "email": email, "password": "hunter2hunter2",
        "display_name": email, "household_name": household,
    })
    return c


def test_owner_can_create_invite_and_invitee_can_accept():
    owner = _signup("karen@example.com", "Karen HQ")
    invitee = _signup("liam@example.com", "Liam HQ")
    try:
        with SessionLocal() as db:
            u = db.query(User).filter_by(email="karen@example.com").one()
            membership = db.query(HouseholdMember).filter_by(user_id=u.id).one()
            karen_hh = membership.household_id

        inv_resp = owner.post(
            f"/api/v1/auth/households/{karen_hh}/invites",
            json={"role": "member"},
        )
        assert inv_resp.status_code == 200, inv_resp.text
        token = inv_resp.json()["token"]

        preview = invitee.get(f"/api/v1/auth/invites/{token}")
        assert preview.status_code == 200
        assert preview.json()["household_name"] == "Karen HQ"
        assert preview.json()["role"] == "member"

        accept = invitee.post(f"/api/v1/auth/invites/{token}/accept")
        assert accept.status_code == 200

        with SessionLocal() as db:
            liam = db.query(User).filter_by(email="liam@example.com").one()
            mems = db.query(HouseholdMember).filter_by(user_id=liam.id).all()
            assert any(m.household_id == karen_hh and m.role == "member" for m in mems)
    finally:
        _cleanup("karen@example.com")
        _cleanup("liam@example.com")


def test_non_owner_cannot_create_invite():
    owner = _signup("mike@example.com", "Mike HQ")
    other = _signup("nina@example.com", "Nina HQ")
    try:
        with SessionLocal() as db:
            mike = db.query(User).filter_by(email="mike@example.com").one()
            mike_hh = db.query(HouseholdMember).filter_by(user_id=mike.id).one().household_id

        resp = other.post(
            f"/api/v1/auth/households/{mike_hh}/invites",
            json={"role": "member"},
        )
        assert resp.status_code == 403
    finally:
        _cleanup("mike@example.com")
        _cleanup("nina@example.com")


def test_revoked_invite_cannot_be_accepted():
    owner = _signup("oscar@example.com", "Oscar HQ")
    invitee = _signup("pam@example.com", "Pam HQ")
    try:
        with SessionLocal() as db:
            o = db.query(User).filter_by(email="oscar@example.com").one()
            oscar_hh = db.query(HouseholdMember).filter_by(user_id=o.id).one().household_id
        created = owner.post(
            f"/api/v1/auth/households/{oscar_hh}/invites",
            json={"role": "member"},
        ).json()
        # Look up the invite id
        with SessionLocal() as db:
            inv = db.query(HouseholdInvite).filter_by(household_id=oscar_hh).order_by(
                HouseholdInvite.created_at.desc()
            ).first()
        rev = owner.delete(
            f"/api/v1/auth/households/{oscar_hh}/invites/{inv.id}"
        )
        assert rev.status_code == 200
        acc = invitee.post(f"/api/v1/auth/invites/{created['token']}/accept")
        assert acc.status_code == 410
    finally:
        _cleanup("oscar@example.com")
        _cleanup("pam@example.com")


def test_already_accepted_invite_returns_410():
    owner = _signup("quinn@example.com", "Quinn HQ")
    invitee = _signup("rose@example.com", "Rose HQ")
    try:
        with SessionLocal() as db:
            q = db.query(User).filter_by(email="quinn@example.com").one()
            q_hh = db.query(HouseholdMember).filter_by(user_id=q.id).one().household_id
        created = owner.post(
            f"/api/v1/auth/households/{q_hh}/invites", json={"role": "member"}
        ).json()
        first = invitee.post(f"/api/v1/auth/invites/{created['token']}/accept")
        assert first.status_code == 200
        second = invitee.post(f"/api/v1/auth/invites/{created['token']}/accept")
        assert second.status_code == 410
    finally:
        _cleanup("quinn@example.com")
        _cleanup("rose@example.com")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_auth_invites.py -v`
Expected: FAIL.

- [ ] **Step 3: Create the invite service**

Create `apps/backend/app/services/auth/invites.py`:

```python
"""Household-invite service — create, look up, accept, revoke."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session as DbSession

from app.models.core import HouseholdInvite, HouseholdMember, User
from app.services.auth.sessions import generate_session_token, hash_session_token

INVITE_TTL_DAYS = 7


def create_invite(
    db: DbSession,
    *,
    household_id,
    role: str,
    created_by_user_id,
    email: str | None = None,
) -> tuple[HouseholdInvite, str]:
    """Mint an invite; return (invite, raw_token)."""
    raw, hashed = generate_session_token()  # reuse the same hash scheme
    inv = HouseholdInvite(
        household_id=household_id,
        token_hash=hashed,
        role=role,
        created_by_user_id=created_by_user_id,
        email=email,
        expires_at=datetime.now(UTC) + timedelta(days=INVITE_TTL_DAYS),
    )
    db.add(inv)
    db.flush()
    return inv, raw


def get_invite_by_raw_token(db: DbSession, raw_token: str) -> HouseholdInvite | None:
    """Look up an invite by its raw token. Returns the row even if expired/accepted/revoked
    so callers can return the right 4xx; redeemability is checked by `is_redeemable`."""
    if not raw_token:
        return None
    return (
        db.query(HouseholdInvite)
        .filter(HouseholdInvite.token_hash == hash_session_token(raw_token))
        .one_or_none()
    )


def is_redeemable(inv: HouseholdInvite) -> bool:
    return (
        inv.accepted_at is None
        and inv.revoked_at is None
        and inv.expires_at > datetime.now(UTC)
    )


def revoke_invite(db: DbSession, inv: HouseholdInvite) -> None:
    if inv.revoked_at is None:
        inv.revoked_at = datetime.now(UTC)
        db.flush()


def accept_invite(db: DbSession, *, inv: HouseholdInvite, user: User) -> HouseholdMember:
    """Add the user as a HouseholdMember; mark the invite accepted."""
    existing = (
        db.query(HouseholdMember)
        .filter(
            HouseholdMember.user_id == user.id,
            HouseholdMember.household_id == inv.household_id,
        )
        .one_or_none()
    )
    if existing is None:
        membership = HouseholdMember(
            user_id=user.id, household_id=inv.household_id, role=inv.role,
        )
        db.add(membership)
    else:
        membership = existing
    inv.accepted_at = datetime.now(UTC)
    inv.accepted_by_user_id = user.id
    db.flush()
    return membership
```

- [ ] **Step 4: Add the invite endpoints to the router**

In `apps/backend/app/routers/auth.py`, update imports:

```python
from app.schemas.auth import (
    CreateHouseholdRequest,
    CreateInviteRequest,
    CreateInviteResponse,
    HouseholdRead,
    InvitePreview,
    LoginRequest,
    LoginResponse,
    MeResponse,
    MembershipRead,
    PasswordChangeRequest,
    SignupRequest,
    SignupResponse,
    SwitchHouseholdRequest,
    UserRead,
)

from app.services.auth import invites as invite_svc
from app.models.core import HouseholdInvite
```

Then append:

```python
def _require_owner(db: Session, *, user: User, household_id) -> None:
    membership = (
        db.query(HouseholdMember)
        .filter(
            HouseholdMember.user_id == user.id,
            HouseholdMember.household_id == household_id,
        )
        .one_or_none()
    )
    if membership is None or membership.role != "owner":
        raise HTTPException(status_code=403, detail="must be a household owner")


@router.post(
    "/households/{household_id}/invites",
    response_model=CreateInviteResponse,
)
def create_invite_endpoint(
    household_id,
    request: CreateInviteRequest,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> CreateInviteResponse:
    """Owner-only. Mint an invite; returns the raw token and a shareable URL (one-time)."""
    _require_owner(db, user=user, household_id=household_id)
    inv, raw = invite_svc.create_invite(
        db, household_id=household_id, role=request.role,
        created_by_user_id=user.id, email=request.email,
    )
    _audit(db, action="auth.invite_created", user_id=user.id,
           payload={"household_id": str(household_id), "invite_id": str(inv.id)})
    db.commit()
    return CreateInviteResponse(
        token=raw,
        url=f"/invite/{raw}",
        expires_at=inv.expires_at,
    )


@router.delete("/households/{household_id}/invites/{invite_id}")
def revoke_invite_endpoint(
    household_id,
    invite_id,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> dict:
    """Owner-only. Revoke an unaccepted invite."""
    _require_owner(db, user=user, household_id=household_id)
    inv = db.get(HouseholdInvite, invite_id)
    if inv is None or inv.household_id != household_id:
        raise HTTPException(status_code=404, detail="invite not found")
    invite_svc.revoke_invite(db, inv)
    _audit(db, action="auth.invite_revoked", user_id=user.id,
           payload={"invite_id": str(inv.id)})
    db.commit()
    return {"status": "revoked"}


@router.get("/invites/{token}", response_model=InvitePreview)
def preview_invite(
    token: str,
    db: Annotated[Session, Depends(get_db)],
    _user: CurrentUser,  # auth required to preview (keeps things simple)
) -> InvitePreview:
    """Preview an invite. 410 if not redeemable, 404 if no such token."""
    inv = invite_svc.get_invite_by_raw_token(db, token)
    if inv is None:
        raise HTTPException(status_code=404, detail="invite not found")
    if not invite_svc.is_redeemable(inv):
        raise HTTPException(status_code=410, detail="invite is no longer redeemable")
    household = db.get(Household, inv.household_id)
    inviter = db.get(User, inv.created_by_user_id)
    return InvitePreview(
        household_name=household.name if household else "",
        role=inv.role,
        inviter_name=inviter.display_name if inviter else None,
        expires_at=inv.expires_at,
    )


@router.post("/invites/{token}/accept", response_model=HouseholdRead)
def accept_invite_endpoint(
    token: str,
    db: Annotated[Session, Depends(get_db)],
    user: CurrentUser,
) -> HouseholdRead:
    """Accept an invite — become a HouseholdMember with the invite's role. 410 if not redeemable."""
    inv = invite_svc.get_invite_by_raw_token(db, token)
    if inv is None:
        raise HTTPException(status_code=404, detail="invite not found")
    if not invite_svc.is_redeemable(inv):
        raise HTTPException(status_code=410, detail="invite is no longer redeemable")
    invite_svc.accept_invite(db, inv=inv, user=user)
    household = db.get(Household, inv.household_id)
    _audit(db, action="auth.invite_accepted", user_id=user.id,
           payload={"invite_id": str(inv.id)})
    db.commit()
    assert household is not None
    return HouseholdRead.model_validate(household)
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_auth_invites.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/app/services/auth/invites.py \
  apps/backend/app/routers/auth.py \
  apps/backend/tests/test_auth_invites.py
git commit -m "feat(auth): add household invite endpoints (create, preview, accept, revoke)"
```

---

### Task 14: `scripts/create_user.py` dev helper

**Files:**
- Create: `apps/backend/scripts/__init__.py`
- Create: `apps/backend/scripts/create_user.py`

- [ ] **Step 1: Create the package marker**

Create `apps/backend/scripts/__init__.py` (empty file).

- [ ] **Step 2: Create the script**

Create `apps/backend/scripts/create_user.py`:

```python
"""Create a user (and household) from the command line, for local development.

Usage:
    uv run python -m scripts.create_user EMAIL PASSWORD DISPLAY_NAME HOUSEHOLD_NAME

If a household with the legacy DEV_HOUSEHOLD_ID already exists (from before the
auth split), pass --adopt-dev to make the new user its owner so existing local
Tier A data stays reachable.
"""
from __future__ import annotations

import argparse
import sys

from app.auth import DEV_HOUSEHOLD_ID
from app.db import SessionLocal
from app.models.core import Household, HouseholdMember, Subscription, User
from app.services.auth.passwords import hash_password


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("email")
    parser.add_argument("password")
    parser.add_argument("display_name")
    parser.add_argument("household_name")
    parser.add_argument(
        "--adopt-dev", action="store_true",
        help="If DEV_HOUSEHOLD_ID exists, make the new user its owner instead of creating a new household.",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        if db.query(User).filter_by(email=args.email.lower()).one_or_none():
            print(f"error: email {args.email} already exists", file=sys.stderr)
            return 1

        user = User(
            email=args.email.lower(),
            hashed_password=hash_password(args.password),
            display_name=args.display_name,
        )
        db.add(user)
        db.flush()

        household = None
        if args.adopt_dev:
            household = db.get(Household, DEV_HOUSEHOLD_ID)
        if household is None:
            household = Household(name=args.household_name)
            db.add(household)
            db.flush()

        db.add(HouseholdMember(
            user_id=user.id, household_id=household.id, role="owner",
        ))
        db.add(Subscription(
            user_id=user.id, plan="free", status="active",
            tier_a_enabled=True, tier_b_enabled=True, tier_s_enabled=False,
        ))
        db.commit()
        print(f"created user {user.email} (id={user.id}) in household {household.name} (id={household.id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Smoke-test the script**

Run: `uv run python -m scripts.create_user smoke@example.com hunter2hunter2 "Smoke" "Smoke HH"`
Expected: prints `created user smoke@example.com ...`. Then clean up:

Run: `uv run python -c "from app.db import SessionLocal; from app.models.core import User, HouseholdMember, Household, Subscription; db = SessionLocal(); u = db.query(User).filter_by(email='smoke@example.com').one(); m = db.query(HouseholdMember).filter_by(user_id=u.id).one(); s = db.query(Subscription).filter_by(user_id=u.id).one(); h = db.get(Household, m.household_id); db.delete(s); db.delete(m); db.delete(h); db.delete(u); db.commit()"`
Expected: no output (clean exit).

- [ ] **Step 4: Commit**

```bash
git add apps/backend/scripts/__init__.py apps/backend/scripts/create_user.py
git commit -m "chore(auth): add scripts/create_user.py for local dev"
```

---

### Task 15: Frontend — `api.ts` auth functions and `credentials: "include"`

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/lib/types.ts`

- [ ] **Step 1: Add auth types**

In `apps/web/src/lib/types.ts`, append at the end:

```typescript
// ---------- Auth ----------

export interface AuthUser {
  id: string;
  email: string;
  display_name: string | null;
}

export interface AuthHousehold {
  id: string;
  name: string;
}

export interface AuthMembership {
  household: AuthHousehold;
  role: string;
}

export interface MeResponse {
  user: AuthUser;
  memberships: AuthMembership[];
  active_household: AuthHousehold | null;
}

export interface SignupResponse {
  user: AuthUser;
  household: AuthHousehold;
}

export interface LoginResponse {
  user: AuthUser;
  active_household: AuthHousehold;
}

export interface InvitePreview {
  household_name: string;
  role: string;
  inviter_name: string | null;
  expires_at: string;
}

export interface CreateInviteResponse {
  token: string;
  url: string;
  expires_at: string;
}
```

- [ ] **Step 2: Update `api.ts` — add `credentials: "include"` and a typed 401**

In `apps/web/src/lib/api.ts`, replace the existing `api()` function and the type-import block with:

```typescript
import type {
  AuthHousehold,
  AuthUser,
  BadgeAward,
  Briefing,
  ChatTurnResponse,
  ContentFeed,
  ContentItem,
  ConversationOpenResponse,
  CookedResponse,
  CreateInviteResponse,
  InventoryItem,
  InvitePreview,
  ItemCaptureResponse,
  ItemCategory,
  LoginResponse,
  MealPlan,
  MeResponse,
  PantryCaptureResponse,
  PantryItem,
  PlannedMealStatus,
  PlannedMealStatusResponse,
  PreservationAdvice,
  PreservationJob,
  PreservationMethod,
  PreservationMethodInfo,
  PurchasedItemResponse,
  RecipeSuggestionsResponse,
  SavingsRollup,
  ShoppingList,
  SignupResponse,
  Streak,
  StretchResponse,
  WasteEvent,
  WeekPlanResponse,
} from "./types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class AuthError extends Error {
  constructor(message = "not authenticated") {
    super(message);
    this.name = "AuthError";
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (res.status === 401) {
    throw new AuthError();
  }
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${await res.text()}`);
  }
  return res.json();
}
```

(Keep all the existing API functions below this block as they are.)

- [ ] **Step 3: Append auth API functions**

At the end of `apps/web/src/lib/api.ts`, append:

```typescript
// ---------- Auth ----------

export function signup(args: {
  email: string;
  password: string;
  display_name: string;
  household_name: string;
}): Promise<SignupResponse> {
  return api<SignupResponse>("/api/v1/auth/signup", {
    method: "POST",
    body: JSON.stringify(args),
  });
}

export function login(email: string, password: string): Promise<LoginResponse> {
  return api<LoginResponse>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function logout(): Promise<{ status: string }> {
  return api<{ status: string }>("/api/v1/auth/logout", { method: "POST" });
}

export function getMe(): Promise<MeResponse> {
  return api<MeResponse>("/api/v1/auth/me");
}

export function changePassword(
  current_password: string,
  new_password: string,
): Promise<{ status: string }> {
  return api<{ status: string }>("/api/v1/auth/password", {
    method: "POST",
    body: JSON.stringify({ current_password, new_password }),
  });
}

export function createHousehold(name: string): Promise<AuthHousehold> {
  return api<AuthHousehold>("/api/v1/auth/households", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function switchHousehold(household_id: string): Promise<AuthHousehold> {
  return api<AuthHousehold>("/api/v1/auth/switch-household", {
    method: "POST",
    body: JSON.stringify({ household_id }),
  });
}

export function createInvite(
  household_id: string,
  role: "member" | "viewer" = "member",
  email?: string,
): Promise<CreateInviteResponse> {
  return api<CreateInviteResponse>(`/api/v1/auth/households/${household_id}/invites`, {
    method: "POST",
    body: JSON.stringify({ role, email }),
  });
}

export function previewInvite(token: string): Promise<InvitePreview> {
  return api<InvitePreview>(`/api/v1/auth/invites/${token}`);
}

export function acceptInvite(token: string): Promise<AuthHousehold> {
  return api<AuthHousehold>(`/api/v1/auth/invites/${token}/accept`, {
    method: "POST",
  });
}

export function revokeInvite(
  household_id: string,
  invite_id: string,
): Promise<{ status: string }> {
  return api<{ status: string }>(
    `/api/v1/auth/households/${household_id}/invites/${invite_id}`,
    { method: "DELETE" },
  );
}
```

- [ ] **Step 4: Verify typecheck**

Run: `cd apps/web && pnpm typecheck`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/api.ts apps/web/src/lib/types.ts
git commit -m "feat(auth): frontend types + API client functions for auth"
```

---

### Task 16: Frontend — `AuthProvider` + `AuthGuard` + layout wire-up

**Files:**
- Create: `apps/web/src/components/AuthProvider.tsx`
- Modify: `apps/web/src/app/layout.tsx`

- [ ] **Step 1: Create the provider**

Create `apps/web/src/components/AuthProvider.tsx`:

```tsx
"use client";

import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { AuthError, getMe } from "@/lib/api";
import type { AuthHousehold, AuthMembership, AuthUser } from "@/lib/types";

interface AuthState {
  ready: boolean;
  user: AuthUser | null;
  memberships: AuthMembership[];
  activeHousehold: AuthHousehold | null;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

const PUBLIC_ROUTES = new Set(["/login", "/signup"]);
function isPublicRoute(path: string): boolean {
  if (PUBLIC_ROUTES.has(path)) return true;
  if (path.startsWith("/invite/")) return true;  // /invite/[token] has its own guard
  return false;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [memberships, setMemberships] = useState<AuthMembership[]>([]);
  const [activeHousehold, setActiveHousehold] = useState<AuthHousehold | null>(null);
  const [ready, setReady] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const me = await getMe();
      setUser(me.user);
      setMemberships(me.memberships);
      setActiveHousehold(me.active_household);
    } catch (err) {
      setUser(null);
      setMemberships([]);
      setActiveHousehold(null);
      if (err instanceof AuthError && !isPublicRoute(pathname)) {
        router.replace("/login");
      }
    } finally {
      setReady(true);
    }
  }, [pathname, router]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const value = useMemo<AuthState>(
    () => ({ ready, user, memberships, activeHousehold, refresh }),
    [ready, user, memberships, activeHousehold, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
```

- [ ] **Step 2: Wire the provider into the layout**

In `apps/web/src/app/layout.tsx`, add this import:

```typescript
import { AuthProvider } from "@/components/AuthProvider";
```

Then replace the `<body>` contents:

```tsx
      <body>
        <div className="flex min-h-screen">
          <Sidebar />
          <main className="min-w-0 flex-1">{children}</main>
        </div>
        <ChatSidebar />
      </body>
```

with:

```tsx
      <body>
        <AuthProvider>
          <div className="flex min-h-screen">
            <Sidebar />
            <main className="min-w-0 flex-1">{children}</main>
          </div>
          <ChatSidebar />
        </AuthProvider>
      </body>
```

- [ ] **Step 3: Verify typecheck**

Run: `cd apps/web && pnpm typecheck`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/AuthProvider.tsx apps/web/src/app/layout.tsx
git commit -m "feat(auth): add AuthProvider + AuthGuard (redirect to /login on 401)"
```

---

### Task 17: Frontend — `/login` and `/signup` pages

**Files:**
- Create: `apps/web/src/app/login/page.tsx`
- Create: `apps/web/src/app/signup/page.tsx`

- [ ] **Step 1: Create the login page**

Create `apps/web/src/app/login/page.tsx`:

```tsx
"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import { login } from "@/lib/api";
import { useAuth } from "@/components/AuthProvider";

export default function LoginPage() {
  const router = useRouter();
  const { refresh } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await login(email, password);
      await refresh();
      router.replace("/");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm px-6 py-20">
      <h1 className="text-3xl font-bold mb-6 text-ink">Log in</h1>
      <form onSubmit={onSubmit} className="space-y-4">
        <label className="block">
          <span className="text-xs text-stone-500">Email</span>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
          />
        </label>
        <label className="block">
          <span className="text-xs text-stone-500">Password</span>
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
          />
        </label>
        {err && (
          <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-800">
            {err}
          </div>
        )}
        <button
          type="submit"
          disabled={busy || !email || !password}
          className="w-full rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-paper transition hover:bg-clay disabled:opacity-50"
        >
          {busy ? "Logging in…" : "Log in"}
        </button>
      </form>
      <p className="mt-6 text-sm text-stone-500">
        No account?{" "}
        <Link href="/signup" className="text-clay underline">
          Sign up
        </Link>
      </p>
    </div>
  );
}
```

- [ ] **Step 2: Create the signup page**

Create `apps/web/src/app/signup/page.tsx`:

```tsx
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import { acceptInvite, signup } from "@/lib/api";
import { useAuth } from "@/components/AuthProvider";

export default function SignupPage() {
  const router = useRouter();
  const search = useSearchParams();
  const returnTo = search.get("return");
  const { refresh } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [householdName, setHouseholdName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await signup({
        email,
        password,
        display_name: displayName,
        household_name: householdName,
      });
      // If signup came from an invite link, accept it now
      if (returnTo && returnTo.startsWith("/invite/")) {
        const token = returnTo.slice("/invite/".length);
        try {
          await acceptInvite(token);
        } catch {
          // Surface but don't block the redirect
        }
      }
      await refresh();
      router.replace(returnTo ?? "/");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm px-6 py-20">
      <h1 className="text-3xl font-bold mb-6 text-ink">Sign up</h1>
      <form onSubmit={onSubmit} className="space-y-4">
        <label className="block">
          <span className="text-xs text-stone-500">Email</span>
          <input
            type="email" required value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
          />
        </label>
        <label className="block">
          <span className="text-xs text-stone-500">Password (min 8)</span>
          <input
            type="password" required minLength={8} value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
          />
        </label>
        <label className="block">
          <span className="text-xs text-stone-500">Display name</span>
          <input
            required value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            className="mt-1 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
          />
        </label>
        <label className="block">
          <span className="text-xs text-stone-500">Household name</span>
          <input
            required value={householdName}
            onChange={(e) => setHouseholdName(e.target.value)}
            placeholder="The Smith household"
            className="mt-1 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
          />
        </label>
        {err && (
          <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-800">
            {err}
          </div>
        )}
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-paper transition hover:bg-clay disabled:opacity-50"
        >
          {busy ? "Creating…" : "Create account"}
        </button>
      </form>
      <p className="mt-6 text-sm text-stone-500">
        Already have an account?{" "}
        <Link href="/login" className="text-clay underline">
          Log in
        </Link>
      </p>
    </div>
  );
}
```

- [ ] **Step 3: Verify typecheck**

Run: `cd apps/web && pnpm typecheck`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/app/login/page.tsx apps/web/src/app/signup/page.tsx
git commit -m "feat(auth): add /login and /signup pages"
```

---

### Task 18: Frontend — Sidebar with active household + switcher + logout

**Files:**
- Modify: `apps/web/src/components/Sidebar.tsx`

- [ ] **Step 1: Replace the Sidebar footer with auth-aware controls**

In `apps/web/src/components/Sidebar.tsx`, change the imports at the top to include the auth helpers:

```typescript
"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { logout, switchHousehold } from "@/lib/api";
import { useAuth } from "@/components/AuthProvider";
```

Then replace the existing `{/* footer */}` block at the bottom of the `<aside>`:

```tsx
      {/* footer */}
      <div className="border-t border-line px-6 py-4">
        <div className="flex items-center gap-2 text-[12px] text-ink-soft">
          <span className="h-2 w-2 rounded-full bg-moss" />
          <span className="font-medium text-ink">Dev Household</span>
        </div>
        <p className="mt-1 text-[11px] text-ink-faint">Hearth v0.1 · pre-launch</p>
      </div>
```

with:

```tsx
      {/* footer */}
      <SidebarFooter />
```

And inside the `Sidebar` component file (after the closing `}` of `Sidebar`), add this new component:

```tsx
function SidebarFooter() {
  const { user, memberships, activeHousehold, refresh } = useAuth();
  const router = useRouter();

  async function onSwitch(id: string) {
    try {
      await switchHousehold(id);
      await refresh();
      router.refresh();
    } catch {
      /* noop — guard will redirect on auth errors */
    }
  }

  async function onLogout() {
    try {
      await logout();
    } finally {
      await refresh();
      router.replace("/login");
    }
  }

  if (!user) {
    return (
      <div className="border-t border-line px-6 py-4">
        <p className="text-[11px] text-ink-faint">Hearth v0.1 · pre-launch</p>
      </div>
    );
  }

  return (
    <div className="border-t border-line px-6 py-4 space-y-2">
      <div className="text-[12px] text-ink-soft">
        <div className="font-medium text-ink">{activeHousehold?.name ?? "—"}</div>
        <div className="text-[11px] text-ink-faint">{user.email}</div>
      </div>
      {memberships.length > 1 && (
        <select
          value={activeHousehold?.id ?? ""}
          onChange={(e) => onSwitch(e.target.value)}
          className="w-full rounded-md border border-line bg-paper px-2 py-1 text-[12px]"
        >
          {memberships.map((m) => (
            <option key={m.household.id} value={m.household.id}>
              {m.household.name}
            </option>
          ))}
        </select>
      )}
      <button
        onClick={onLogout}
        className="w-full rounded-md border border-line bg-paper px-2 py-1 text-[12px] text-ink-soft hover:bg-raised"
      >
        Log out
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Verify typecheck**

Run: `cd apps/web && pnpm typecheck`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/Sidebar.tsx
git commit -m "feat(auth): sidebar shows active household, switcher, and logout"
```

---

### Task 19: Frontend — `ChatSidebar` resets on household switch

**Files:**
- Modify: `apps/web/src/components/ChatSidebar.tsx`

- [ ] **Step 1: Add the active-household dep to the conversation effect**

In `apps/web/src/components/ChatSidebar.tsx`, add the auth import alongside the existing imports:

```typescript
import { useAuth } from "@/components/AuthProvider";
```

Inside the `ChatSidebar` component, add this line right after `const pathname = usePathname();`:

```typescript
  const { activeHousehold } = useAuth();
```

Then locate the existing `useEffect` whose dependency array is `[open, pathname]` and change it to `[open, pathname, activeHousehold?.id]`. The full hook should read:

```typescript
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setConvId(null);
    setMsgs([]);
    setError(null);
    openConversation(pathname)
      .then((res) => {
        if (cancelled) return;
        setConvId(res.conversation_id);
        setMsgs(
          res.messages.map((m) => ({
            role: m.role,
            content: m.content,
            actions: (m.payload?.results as ActionResult[] | undefined) ?? undefined,
          })),
        );
      })
      .catch(() => {
        if (!cancelled) setError("Couldn't load the assistant.");
      });
    return () => {
      cancelled = true;
    };
  }, [open, pathname, activeHousehold?.id]);
```

- [ ] **Step 2: Verify typecheck**

Run: `cd apps/web && pnpm typecheck`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/ChatSidebar.tsx
git commit -m "feat(auth): reset chat conversation on household switch"
```

---

### Task 20: Frontend — `/invite/[token]` page

**Files:**
- Create: `apps/web/src/app/invite/[token]/page.tsx`

- [ ] **Step 1: Create the page**

Create `apps/web/src/app/invite/[token]/page.tsx`:

```tsx
"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { acceptInvite, AuthError, previewInvite } from "@/lib/api";
import { useAuth } from "@/components/AuthProvider";
import type { InvitePreview as InvitePreviewT } from "@/lib/types";

export default function InvitePage() {
  const params = useParams<{ token: string }>();
  const token = params.token;
  const router = useRouter();
  const { user, ready, refresh } = useAuth();
  const [preview, setPreview] = useState<InvitePreviewT | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // If not authed once auth state is ready, send to signup with a return path.
  useEffect(() => {
    if (ready && !user) {
      router.replace(`/signup?return=/invite/${token}`);
    }
  }, [ready, user, router, token]);

  // Load the preview once authenticated.
  useEffect(() => {
    if (!user) return;
    previewInvite(token)
      .then(setPreview)
      .catch((e) => {
        if (e instanceof AuthError) return; // guard handles
        setError((e as Error).message);
      });
  }, [user, token]);

  async function onAccept() {
    setBusy(true);
    setError(null);
    try {
      await acceptInvite(token);
      await refresh();
      router.replace("/");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!ready || !user) return null;

  return (
    <div className="mx-auto max-w-md px-6 py-20">
      <h1 className="text-2xl font-bold mb-4 text-ink">Household invite</h1>
      {error && (
        <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-800">
          {error}
        </div>
      )}
      {preview && (
        <>
          <p className="mb-2 text-stone-700">
            {preview.inviter_name ?? "Someone"} invited you to join{" "}
            <span className="font-semibold">{preview.household_name}</span> as{" "}
            <span className="font-mono">{preview.role}</span>.
          </p>
          <button
            onClick={onAccept}
            disabled={busy}
            className="mt-4 w-full rounded-lg bg-ink px-4 py-2 text-sm font-semibold text-paper transition hover:bg-clay disabled:opacity-50"
          >
            {busy ? "Accepting…" : "Accept invite"}
          </button>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify typecheck**

Run: `cd apps/web && pnpm typecheck`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/app/invite/
git commit -m "feat(auth): add /invite/[token] preview and accept page"
```

---

### Task 21: Full verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full backend test suite**

Run: `cd apps/backend && uv run pytest -q`
Expected: all tests pass — the prior 213 (preserved by the conftest override) plus the new auth-flow tests (model, passwords, sessions, signup, login, logout/me, password, create-household, switch-household, invites). Approximately **235 passed, 1 skipped**, zero failures.

- [ ] **Step 2: Run ruff + mypy on Phase 1 + auth code**

Run: `cd apps/backend && uv run ruff check .`
Expected: clean (or auto-fixable formatting; run `uv run ruff check --fix .` if needed and commit the fix).

Run: `uv run mypy app`
Expected: pre-existing errors in `app/config.py`, `app/db.py`, `app/services/ingredients.py` may remain; **no new errors** in any auth file (`app/auth.py`, `app/services/auth/`, `app/routers/auth.py`, `app/schemas/auth.py`, the new `core.py` additions).

- [ ] **Step 3: Verify the migration round-trips**

Run: `cd apps/backend && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: downgrade drops the auth tables/columns cleanly; upgrade recreates them. No errors.

- [ ] **Step 4: Run the frontend type check and build**

Run: `cd apps/web && pnpm typecheck && pnpm build`
Expected: typecheck passes; build succeeds. The output should list `/login`, `/signup`, and `/invite/[token]` among the routes.

- [ ] **Step 5: Smoke-test the running app (recommended)**

Run `./frugal up` (in the worktree). Open `http://localhost:3000` — the auth guard should redirect to `/login`. Click "Sign up" → create an account → land on `/` → the sidebar footer shows your household + your email + a Log out button. Try creating a second household via the API (`POST /api/v1/auth/households`), then watch the switcher appear in the sidebar and switching it. Log out → guard redirects back to `/login`. Then `./frugal down`.

- [ ] **Step 6: Commit any lint/format fixes**

```bash
git add -A
git commit -m "chore(auth): apply lint and format fixes"
```

(Skip this commit if Steps 1–4 produced no changes.)

---

## Self-Review

**Spec coverage** — every section of `2026-05-22-real-auth-multi-household-design.md` maps to a task:
- §3 resolved decisions → §1, §4, §6 (cookie attrs); §3, §6 (CSRF/throttling); §3, §10 (password change); §11 (signup subscription); §13 (audit logging).
- §4 data model → Task 2 (Session/HouseholdInvite/User columns + migration).
- §5 auth mechanics → Tasks 3 (passwords), 4 (sessions + cookies), 6 (dependency swap).
- §6 security posture → CSRF posture (`SameSite=Lax` settings + CORS already in `main.py`); throttling Task 8; password policy in schemas Task 7/10; token hashing Tasks 4/13; password-change-revokes Task 10.
- §7 API surface → Tasks 7 (signup), 8 (login), 9 (logout, me), 10 (password), 11 (create household), 12 (switch), 13 (invites).
- §8 multi-household → Tasks 11–13.
- §9 stub replacement + test strategy → Task 5 (conftest), Task 6 (auth.py + main.py), Task 14 (create_user script).
- §10 frontend → Tasks 15 (api/types), 16 (provider/guard), 17 (login/signup), 18 (sidebar), 19 (chat), 20 (invite).
- §11 migration → Task 2; §12 testing → woven into each task + Task 21.

**Placeholder scan** — no TBDs; every code step shows complete content; every command states expected output.

**Type consistency** — `Session` / `HouseholdInvite` model field names match between Task 2 (model), Task 4 (service), Task 13 (invite service), and all router consumers. Schema names (`SignupRequest`/`SignupResponse`/`LoginResponse`/`MeResponse`/`HouseholdRead`/`UserRead`/`MembershipRead`/`PasswordChangeRequest`/`CreateHouseholdRequest`/`SwitchHouseholdRequest`/`CreateInviteRequest`/`CreateInviteResponse`/`InvitePreview`) are defined in Task 7 and consumed unchanged in later tasks. The `_audit(...)` helper, `_require_owner(...)` helper, and `session_svc`/`invite_svc` aliases keep the same shape across all router tasks. Frontend `AuthUser`/`AuthHousehold`/`AuthMembership`/`MeResponse`/`SignupResponse`/`LoginResponse`/`InvitePreview`/`CreateInviteResponse` are defined in Task 15 and consumed in Tasks 16–20.
