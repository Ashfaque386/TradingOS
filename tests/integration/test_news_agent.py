"""REL-010 E10.3: real RSS ingestion against the two confirmed-working free financial news
feeds (no API key needed, so no skip-if-no-credential gate is needed here, unlike the broker
sandbox tests)."""

from src.agents.nodes.news_agent import REAL_NEWS_FEEDS, ingest_news_cycle


def test_ingest_news_cycle_returns_real_parsed_items_from_the_real_feeds():
    items = ingest_news_cycle()

    assert len(items) >= 1
    first = items[0]
    assert first.title
    assert first.url.startswith("http")
    assert first.source in REAL_NEWS_FEEDS


def test_ingest_news_cycle_dedupes_within_a_single_call():
    items = ingest_news_cycle()
    keys = [(item.source, item.guid) for item in items]
    assert len(keys) == len(set(keys))


def test_ingest_news_cycle_handles_an_unreachable_feed_gracefully():
    items = ingest_news_cycle({"broken": "https://this-domain-does-not-exist.invalid/rss.xml"})
    assert items == []
