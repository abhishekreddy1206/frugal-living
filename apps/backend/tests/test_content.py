"""End-to-end tests for the content capture + feed endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models.content import ContentItem
from app.models.core import Event
from app.routers import content as content_router
from app.services.youtube import YouTubeMetadata, parse_video_id

VIDEO_A = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
VIDEO_B = "https://youtu.be/9bZkp7q19f0"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_youtube(monkeypatch):
    """Replace the network oEmbed call with deterministic metadata per video id."""

    def fake_fetch(url: str) -> YouTubeMetadata:
        video_id = parse_video_id(url)
        assert video_id is not None
        return YouTubeMetadata(
            video_id=video_id,
            url=f"https://www.youtube.com/watch?v={video_id}",
            title=f"Frugal cooking — {video_id}",
            author="Test Channel",
            thumbnail_url=f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        )

    monkeypatch.setattr(content_router, "fetch_youtube_metadata", fake_fetch)
    return fake_fetch


def test_capture_creates_item_and_emits_event(client, mock_youtube):
    resp = client.post("/api/v1/content/capture", json={"url": VIDEO_A})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "youtube"
    assert body["external_id"] == "dQw4w9WgXcQ"
    assert body["title"] == "Frugal cooking — dQw4w9WgXcQ"
    assert body["author"] == "Test Channel"
    assert body["thumbnail_url"].endswith("/dQw4w9WgXcQ/hqdefault.jpg")
    assert body["topic"] == "food"

    with SessionLocal() as db:
        events = (
            db.query(Event).filter(Event.event_type == "content.item.captured").all()
        )
        assert len(events) == 1
        assert events[0].payload["external_id"] == "dQw4w9WgXcQ"


def test_capture_rejects_non_youtube_url(client, mock_youtube):
    resp = client.post("/api/v1/content/capture", json={"url": "https://example.com/blog"})
    assert resp.status_code == 422
    assert "YouTube" in resp.json()["detail"]


def test_capture_propagates_unresolvable_video(client, monkeypatch):
    def boom(url: str) -> YouTubeMetadata:
        raise ValueError("YouTube could not resolve that video (private or removed?)")

    monkeypatch.setattr(content_router, "fetch_youtube_metadata", boom)
    resp = client.post("/api/v1/content/capture", json={"url": VIDEO_A})
    assert resp.status_code == 422
    assert "private or removed" in resp.json()["detail"]


def test_capture_is_idempotent_on_duplicate(client, mock_youtube):
    first = client.post("/api/v1/content/capture", json={"url": VIDEO_A})
    second = client.post("/api/v1/content/capture", json={"url": VIDEO_A})
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    with SessionLocal() as db:
        rows = db.query(ContentItem).filter(ContentItem.external_id == "dQw4w9WgXcQ").all()
        assert len(rows) == 1


def test_feed_lists_captured_newest_first(client, mock_youtube):
    client.post("/api/v1/content/capture", json={"url": VIDEO_A})
    client.post("/api/v1/content/capture", json={"url": VIDEO_B})

    resp = client.get("/api/v1/content/feed")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    # VIDEO_B was captured last, so it sorts first.
    assert body["items"][0]["external_id"] == "9bZkp7q19f0"
    assert body["items"][1]["external_id"] == "dQw4w9WgXcQ"


def test_delete_soft_deletes_and_drops_from_feed(client, mock_youtube):
    captured = client.post("/api/v1/content/capture", json={"url": VIDEO_A}).json()
    item_id = captured["id"]

    deleted = client.delete(f"/api/v1/content/items/{item_id}")
    assert deleted.status_code == 200

    feed = client.get("/api/v1/content/feed").json()
    assert feed["count"] == 0

    # Row still exists, just soft-deleted.
    with SessionLocal() as db:
        row = db.get(ContentItem, item_id)
        assert row is not None
        assert row.deleted_at is not None

    # Deleting again is a 404.
    assert client.delete(f"/api/v1/content/items/{item_id}").status_code == 404


def test_recapture_after_delete_restores_item(client, mock_youtube):
    captured = client.post("/api/v1/content/capture", json={"url": VIDEO_A}).json()
    client.delete(f"/api/v1/content/items/{captured['id']}")

    recaptured = client.post("/api/v1/content/capture", json={"url": VIDEO_A})
    assert recaptured.status_code == 200
    assert recaptured.json()["id"] == captured["id"]
    assert client.get("/api/v1/content/feed").json()["count"] == 1
