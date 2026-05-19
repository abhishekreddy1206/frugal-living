"""
Reddit ingestion — pulls top/hot threads from configured subreddits.

Suggested starter subreddits to seed (`content.sources` rows):
  - r/Frugal
  - r/EatCheapAndHealthy
  - r/MealPrepSunday
  - r/Cooking
  - r/Pantry
  - r/Preppers (selectively — frugal angle only)
  - r/ZeroWaste

Implementation plan:
  1. Authenticate with Reddit using PRAW (client_id + secret + user_agent).
  2. For each active subreddit source, fetch top posts from the last week.
  3. For each post, capture title, body, top N comments.
  4. Upsert ContentItem(provider=reddit, external_id=t3_postid, body=combined text,
     author, published_at).
  5. Send through Claude to summarize and tag (e.g. "pantry stretch", "freezer hack").
"""
from app.config import settings


def run_ingestion(source_id: str | None = None) -> dict:
    """Stub. Implement when Reddit credentials are configured."""
    if not (settings.reddit_client_id and settings.reddit_client_secret):
        return {"status": "skipped", "reason": "Reddit credentials not configured"}
    raise NotImplementedError("Implement Reddit ingestion")
