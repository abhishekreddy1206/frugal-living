"""
YouTube ingestion — pulls latest videos from configured frugal-living channels.

Suggested starter channels to seed (`content.sources` rows):
  - Pro Home Cooks
  - The Frugal Chef
  - Frugal Fit Mom
  - Brian Lagerstrom
  - Sorted Food
  - Adam Ragusea
  - Pasta Grannies

Implementation plan:
  1. For each active YouTube source, call YouTube Data API v3 `search.list` filtered
     by channelId + publishedAfter=last_ingested_at.
  2. For each new video, fetch its transcript (youtube-transcript-api or captions API).
  3. Upsert ContentItem(provider=youtube, external_id=video_id, body=transcript,
     duration_seconds, thumbnail_url, published_at).
  4. Optionally extract recipes from transcript via Claude and store as Recipe rows
     with imported_from_content_id pointing back.
"""
from app.config import settings


def run_ingestion(source_id: str | None = None) -> dict:
    """Stub. Implement when YOUTUBE_API_KEY is set and ContentSource seeded."""
    if not settings.youtube_api_key:
        return {"status": "skipped", "reason": "YOUTUBE_API_KEY not configured"}
    raise NotImplementedError("Implement YouTube ingestion")
