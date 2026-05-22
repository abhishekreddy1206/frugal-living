"""
YouTube content — capture a single video by URL, and (future) channel polling.

`fetch_youtube_metadata` resolves a YouTube URL to title/author/thumbnail using
the public oEmbed endpoint (no API key needed). Channel polling (`run_ingestion`)
still requires the YouTube Data API and is left for a later sprint.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_OEMBED_URL = "https://www.youtube.com/oembed"
_DATA_API_URL = "https://www.googleapis.com/youtube/v3/videos"
_ISO8601_DURATION_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")

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


def _parse_iso8601_duration(value: str | None) -> int | None:
    """Convert a YouTube ISO-8601 duration ('PT5M30S') to total seconds."""
    if not value:
        return None
    match = _ISO8601_DURATION_RE.fullmatch(value)
    if match is None:
        return None
    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


@dataclass
class VideoDetails:
    """Rich video metadata from the YouTube Data API."""

    title: str
    author: str | None
    description: str
    youtube_tags: list[str]
    duration_seconds: int | None
    published_at: datetime | None


def fetch_video_details(video_id: str) -> VideoDetails | None:
    """Fetch rich metadata via the YouTube Data API. Returns None when no API key
    is configured, or the call fails, or the video isn't found — callers fall back."""
    if not settings.youtube_api_key:
        return None
    try:
        resp = httpx.get(
            _DATA_API_URL,
            params={
                "part": "snippet,contentDetails",
                "id": video_id,
                "key": settings.youtube_api_key,
            },
            timeout=10.0,
        )
    except httpx.HTTPError as e:
        logger.warning("YouTube Data API request failed for %s: %s", video_id, e)
        return None
    if resp.status_code != 200:
        logger.warning("YouTube Data API returned %s for %s", resp.status_code, video_id)
        return None
    try:
        data = resp.json()
    except ValueError:
        logger.warning("YouTube Data API returned an unreadable body for %s", video_id)
        return None
    items = data.get("items") if isinstance(data, dict) else None
    if not items:
        logger.warning("YouTube Data API found no video for %s", video_id)
        return None

    snippet = items[0].get("snippet") or {}
    content_details = items[0].get("contentDetails") or {}
    published_at: datetime | None = None
    published_raw = snippet.get("publishedAt")
    if published_raw:
        try:
            published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
        except ValueError:
            published_at = None

    return VideoDetails(
        title=snippet.get("title") or "Untitled video",
        author=snippet.get("channelTitle"),
        description=snippet.get("description") or "",
        youtube_tags=list(snippet.get("tags") or []),
        duration_seconds=_parse_iso8601_duration(content_details.get("duration")),
        published_at=published_at,
    )


@dataclass
class VideoMetadata:
    """Unified capture metadata. description/youtube_tags/duration/published_at are
    populated only when the Data API resolved the video; oEmbed fills the rest."""

    video_id: str
    url: str
    title: str
    author: str | None
    thumbnail_url: str
    description: str | None
    youtube_tags: list[str] = field(default_factory=list)
    duration_seconds: int | None = None
    published_at: datetime | None = None


def resolve_video_metadata(url: str) -> VideoMetadata:
    """Resolve a YouTube URL to capture metadata — Data API first (rich), oEmbed
    fallback (title/author/thumbnail only). Raises ValueError if neither resolves."""
    video_id = parse_video_id(url.strip())
    if video_id is None:
        raise ValueError("Not a recognizable YouTube video URL")
    canonical = f"https://www.youtube.com/watch?v={video_id}"
    thumbnail = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

    details = fetch_video_details(video_id)
    if details is not None:
        return VideoMetadata(
            video_id=video_id,
            url=canonical,
            title=details.title,
            author=details.author,
            thumbnail_url=thumbnail,
            description=details.description,
            youtube_tags=details.youtube_tags,
            duration_seconds=details.duration_seconds,
            published_at=details.published_at,
        )

    oembed = fetch_youtube_metadata(canonical)  # raises ValueError if this also fails
    return VideoMetadata(
        video_id=video_id,
        url=oembed.url,
        title=oembed.title,
        author=oembed.author,
        thumbnail_url=oembed.thumbnail_url,
        description=None,
    )


def run_ingestion(source_id: str | None = None) -> dict:
    """Stub — channel polling needs the YouTube Data API. Later sprint."""
    if not settings.youtube_api_key:
        return {"status": "skipped", "reason": "YOUTUBE_API_KEY not configured"}
    raise NotImplementedError("Implement YouTube channel ingestion")
