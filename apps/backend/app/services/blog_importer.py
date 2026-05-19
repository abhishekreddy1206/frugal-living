"""
Blog/RSS importer — pulls posts from frugal recipe blogs and parses recipes.

Suggested starter feeds to seed (`content.sources` rows with provider=rss):
  - Budget Bytes (https://www.budgetbytes.com/feed/)
  - The Kitchn (https://www.thekitchn.com/main.rss)
  - Serious Eats (https://www.seriouseats.com/feed)
  - Pinch of Yum (https://pinchofyum.com/feed)
  - Cookie + Kate (https://cookieandkate.com/feed)
  - NYT Cooking — paywalled, sample lightly via public previews only

Implementation plan:
  1. For each active RSS source, fetch the feed (feedparser).
  2. For each new entry, fetch the article HTML, extract content (trafilatura
     or readability-lxml), and parse recipe schema.org JSON-LD if present.
  3. Upsert ContentItem(provider=rss, external_id=entry_id, body=article_text).
  4. If recipe schema is found, create a Recipe with attribution back to the source.
  5. Respect robots.txt and rate limit; cache aggressively.

Attribution rule: always preserve source_url and source_attribution on derived Recipe rows.
"""


def run_ingestion(source_id: str | None = None) -> dict:
    """Stub. Implement RSS polling + article extraction."""
    raise NotImplementedError("Implement blog/RSS importer")
