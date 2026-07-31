"""News Agent (AGT-013, REL-010 E10.3).

Real RSS ingestion over two confirmed-working, free financial news feeds (verified for real at
implementation time -- both return genuine, current article XML, not guessed URLs):
Moneycontrol's latest-news feed and Economic Times' Markets feed. No API key needed for either.

Deterministic, no LLM call in this module -- an adapter fetches and normalizes, it doesn't
interpret, matching src/data/ingest/bhavcopy.py's own established split of concerns. Sentiment
scoring is a separate, deliberate step (src/agents/nodes/sentiment_agent.py, AGT-014).
"""

from dataclasses import dataclass
from datetime import UTC, datetime

import feedparser
import structlog

logger = structlog.get_logger(__name__)

REAL_NEWS_FEEDS = {
    "moneycontrol": "https://www.moneycontrol.com/rss/latestnews.xml",
    "economic_times_markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
}


@dataclass(frozen=True)
class NewsItem:
    title: str
    summary: str
    source: str
    url: str
    published_at: datetime | None
    guid: str


def _parse_entry(source: str, entry: "feedparser.FeedParserDict") -> NewsItem:
    published_at = None
    struct = getattr(entry, "published_parsed", None)
    if struct:
        year, month, day, hour, minute, second = struct[:6]
        published_at = datetime(year, month, day, hour, minute, second, tzinfo=UTC)
    return NewsItem(
        title=entry.get("title", ""),
        summary=entry.get("summary", ""),
        source=source,
        url=entry.get("link", ""),
        published_at=published_at,
        guid=entry.get("id") or entry.get("link", ""),
    )


def ingest_news_cycle(feeds: dict[str, str] | None = None) -> list[NewsItem]:
    """Fetches every feed in `feeds` (defaults to `REAL_NEWS_FEEDS`), deduping on
    `(source, guid)` within this single call -- cross-run dedup against already-processed items
    is the caller's job (e.g. the Sentiment Agent checking Qdrant before scoring), this function
    just normalizes what each feed returned into real `NewsItem`s."""
    real_feeds = feeds if feeds is not None else REAL_NEWS_FEEDS
    seen: set[tuple[str, str]] = set()
    items: list[NewsItem] = []

    for source, url in real_feeds.items():
        try:
            parsed = feedparser.parse(url)
            if parsed.bozo:
                logger.warning(
                    "news_feed_parse_warning", source=source, error=str(parsed.bozo_exception)
                )
            for entry in parsed.entries:
                item = _parse_entry(source, entry)
                key = (source, item.guid)
                if key in seen:
                    continue
                seen.add(key)
                items.append(item)
        except Exception as exc:  # noqa: BLE001 - one feed failing must not sink the whole cycle
            logger.warning("news_feed_fetch_failed", source=source, error=str(exc))

    return items
