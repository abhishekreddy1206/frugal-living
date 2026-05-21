"""Unit tests for the YouTube metadata service (network boundary mocked)."""
from __future__ import annotations

import json

import pytest

from app.services import youtube

VIDEO_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


class _FakeResponse:
    """Minimal stand-in for httpx.Response — only what fetch_youtube_metadata reads."""

    def __init__(self, status_code: int, payload, *, raises: Exception | None = None):
        self.status_code = status_code
        self._payload = payload
        self._raises = raises

    def json(self):
        if self._raises is not None:
            raise self._raises
        return self._payload


def test_fetch_metadata_rejects_non_object_oembed_body(monkeypatch):
    """A 200 response whose JSON body isn't an object must raise ValueError, not crash.

    Previously the body was passed straight to ``data.get(...)``, so a list/string
    payload raised AttributeError and surfaced as an HTTP 500.
    """
    monkeypatch.setattr(
        youtube.httpx, "get", lambda *a, **k: _FakeResponse(200, ["not", "an", "object"])
    )
    with pytest.raises(ValueError):
        youtube.fetch_youtube_metadata(VIDEO_URL)


def test_fetch_metadata_rejects_unparseable_oembed_body(monkeypatch):
    """A 200 response with a non-JSON body must surface a clean message.

    json.JSONDecodeError is already a ValueError, so it reaches the caller — but
    its raw text ("Expecting value: line 1 ...") must not leak as the API error.
    """
    monkeypatch.setattr(
        youtube.httpx,
        "get",
        lambda *a, **k: _FakeResponse(
            200, None, raises=json.JSONDecodeError("Expecting value", "", 0)
        ),
    )
    with pytest.raises(ValueError) as exc:
        youtube.fetch_youtube_metadata(VIDEO_URL)
    assert "Expecting value" not in str(exc.value)
