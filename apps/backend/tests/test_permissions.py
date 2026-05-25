"""Pure-function tests for permission helpers — no DB required."""
from datetime import UTC, datetime

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
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
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
