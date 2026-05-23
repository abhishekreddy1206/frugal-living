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
