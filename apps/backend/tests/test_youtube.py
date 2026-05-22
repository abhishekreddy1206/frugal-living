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


def _data_api_payload(*, description="", tags=None, duration="PT5M30S"):
    return {
        "items": [
            {
                "snippet": {
                    "title": "Frugal Tomato Pasta",
                    "channelTitle": "Test Channel",
                    "description": description,
                    "tags": tags or [],
                    "publishedAt": "2026-01-15T12:00:00Z",
                },
                "contentDetails": {"duration": duration},
            }
        ]
    }


def test_fetch_video_details_returns_none_without_key(monkeypatch):
    monkeypatch.setattr(youtube.settings, "youtube_api_key", "")
    assert youtube.fetch_video_details("dQw4w9WgXcQ") is None


def test_fetch_video_details_parses_payload(monkeypatch):
    monkeypatch.setattr(youtube.settings, "youtube_api_key", "test-key")
    monkeypatch.setattr(
        youtube.httpx,
        "get",
        lambda *a, **k: _FakeResponse(200, _data_api_payload(description="Uses tomato and pasta.")),
    )
    details = youtube.fetch_video_details("dQw4w9WgXcQ")
    assert details is not None
    assert details.description == "Uses tomato and pasta."
    assert details.duration_seconds == 330
    assert details.author == "Test Channel"


def test_fetch_video_details_returns_none_on_error(monkeypatch):
    monkeypatch.setattr(youtube.settings, "youtube_api_key", "test-key")
    monkeypatch.setattr(youtube.httpx, "get", lambda *a, **k: _FakeResponse(403, {}))
    assert youtube.fetch_video_details("dQw4w9WgXcQ") is None


def test_resolve_video_metadata_prefers_data_api(monkeypatch):
    monkeypatch.setattr(youtube.settings, "youtube_api_key", "test-key")
    monkeypatch.setattr(
        youtube.httpx,
        "get",
        lambda *a, **k: _FakeResponse(200, _data_api_payload(description="desc")),
    )
    meta = youtube.resolve_video_metadata(VIDEO_URL)
    assert meta.description == "desc"
    assert meta.video_id == "dQw4w9WgXcQ"


def test_resolve_video_metadata_falls_back_to_oembed(monkeypatch):
    monkeypatch.setattr(youtube.settings, "youtube_api_key", "")  # no key -> no Data API

    def fake_oembed(url):
        return youtube.YouTubeMetadata(
            video_id="dQw4w9WgXcQ",
            url=url,
            title="oEmbed title",
            author="oEmbed author",
            thumbnail_url="https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        )

    monkeypatch.setattr(youtube, "fetch_youtube_metadata", fake_oembed)
    meta = youtube.resolve_video_metadata(VIDEO_URL)
    assert meta.title == "oEmbed title"
    assert meta.description is None


def test_fetch_video_details_returns_none_on_connection_error(monkeypatch):
    """fetch_video_details must never raise — a transport error returns None."""
    monkeypatch.setattr(youtube.settings, "youtube_api_key", "test-key")

    def boom(*args, **kwargs):
        raise youtube.httpx.ConnectError("simulated connection failure")

    monkeypatch.setattr(youtube.httpx, "get", boom)
    assert youtube.fetch_video_details("dQw4w9WgXcQ") is None
