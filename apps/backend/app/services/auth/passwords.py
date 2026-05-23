"""Password hashing and verification via passlib's bcrypt backend."""
from __future__ import annotations

from passlib.context import CryptContext  # type: ignore[import-untyped]

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of the plaintext password."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True iff `plain` matches the stored bcrypt hash."""
    return _pwd_context.verify(plain, hashed)
