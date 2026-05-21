"""
YouTube content — capture a single video by URL, and (future) channel polling.

`fetch_youtube_metadata` resolves a YouTube URL to title/author/thumbnail using
the public oEmbed endpoint (no API key needed). Channel polling (`run_ingestion`)
still requires the YouTube Data API and is left for a later sprint.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from app.config import settings

_OEMBED_URL = "https://www.youtube.com/oembed"

# Matches the 11-char video id across watch / youtu.be / shorts / embed URLs.
_VIDEO_ID_PATTERNS = [
    re.compile(r"youtube\.com/watch\?(?:.*&)?v=([A-Za-z0-9_-]{11})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/shorts/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/embed/([A-Za-z0-9_-]{11})"),
]


@dataclass
class YouTubeMetadata:
    video_id: str
    url: str  # canonical watch URL
    title: str
    author: str | None
    thumbnail_url: str


def parse_video_id(url: str) -> str | None:
    """Pull the video id out of any common YouTube URL form, or return None."""
    for pattern in _VIDEO_ID_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return None


def fetch_youtube_metadata(url: str) -> YouTubeMetadata:
    """Resolve a YouTube URL to structured metadata via the oEmbed endpoint.

    Raises ValueError if the URL isn't a recognizable YouTube video or the
    video can't be resolved (private, deleted, geo-blocked).
    """
    video_id = parse_video_id(url.strip())
    if video_id is None:
        raise ValueError("Not a recognizable YouTube video URL")

    canonical = f"https://www.youtube.com/watch?v={video_id}"
    try:
        resp = httpx.get(
            _OEMBED_URL,
            params={"url": canonical, "format": "json"},
            timeout=10.0,
            follow_redirects=True,
        )
    except httpx.HTTPError as e:
        raise ValueError(f"Could not reach YouTube: {e}") from e

    if resp.status_code != 200:
        raise ValueError("YouTube could not resolve that video (private or removed?)")

    # A 200 is no guarantee of a well-formed oEmbed payload — proxies, captcha
    # walls and outages all return 200 with an unexpected body. Parse defensively
    # so the caller always sees a clean ValueError (→ HTTP 422), never a 500.
    try:
        data = resp.json()
    except ValueError as e:
        raise ValueError("YouTube returned an unreadable response for that video") from e
    if not isinstance(data, dict):
        raise ValueError("YouTube returned an unexpected response for that video")

    return YouTubeMetadata(
        video_id=video_id,
        url=canonical,
        title=data.get("title") or "Untitled video",
        author=data.get("author_name"),
        # i.ytimg hqdefault is always available at a predictable 480x360.
        thumbnail_url=f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
    )


def run_ingestion(source_id: str | None = None) -> dict:
    """Stub — channel polling needs the YouTube Data API. Later sprint."""
    if not settings.youtube_api_key:
        return {"status": "skipped", "reason": "YOUTUBE_API_KEY not configured"}
    raise NotImplementedError("Implement YouTube channel ingestion")
