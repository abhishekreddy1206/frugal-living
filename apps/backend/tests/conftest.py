"""
Shared pytest fixtures.

Tests run against the real local Postgres (per CLAUDE.md: do NOT use SQLite —
we rely on JSONB and array types). Each test runs inside a transaction that's
rolled back at teardown, so tests don't leak rows.

The starter ingredient catalog and dev household are seeded once at the start of
the session (idempotent) so resolver tests have a stable backdrop to query against.
"""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.auth import seed_dev_fixtures
from app.db import SessionLocal, engine


@pytest.fixture(scope="session", autouse=True)
def _seed_session_fixtures():
    """Ensure dev household + ingredient catalog exist for all tests in this run."""
    seed_dev_fixtures()


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
