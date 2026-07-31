"""Sentiment Agent (AGT-014, PMPT-040/041, REL-010 E10.3).

Scores real news items (from src/agents/nodes/news_agent.py) via a real LLM call using the
already-existing `sentiment` task-type chain (src/agents/routing.yaml), then persists the result
into the `news_sentiment` Qdrant collection (src/memory/news_memory.py) -- a collection reserved
since Phase 2 but never written to until this epic.
"""

import json
from dataclasses import dataclass

import structlog

from src.agents.llm_router import complete
from src.agents.nodes.common import extract_json
from src.agents.nodes.news_agent import NewsItem
from src.agents.prompt_registry import get_active_prompt
from src.memory.news_memory import ingest_news_sentiment

PROMPT_SLUG = "sentiment_agent"
TASK_PROMPT_SLUG = "sentiment_agent_task"
logger = structlog.get_logger(__name__)

_VALID_SENTIMENTS = {"Bullish", "Bearish", "Neutral"}


@dataclass(frozen=True)
class _SentimentResult:
    sentiment: str
    confidence: float
    symbols_mentioned: list[str]


def score_and_store_sentiment(items: list[NewsItem]) -> list[str]:
    """Scores each item and upserts it into `news_sentiment`. A single item's LLM/parse failure
    is logged and skipped, not fatal to the whole batch -- returns the Qdrant point IDs actually
    written (may be shorter than `items` if some were skipped)."""
    point_ids: list[str] = []
    for item in items:
        try:
            result = _score_one(item)
        except Exception as exc:  # noqa: BLE001 - one bad item must not sink the whole cycle
            logger.warning("sentiment_scoring_failed", title=item.title, error=str(exc))
            continue

        point_id = ingest_news_sentiment(
            title=item.title,
            summary=item.summary,
            source=item.source,
            url=item.url,
            published_at=item.published_at,
            sentiment=result.sentiment,
            confidence=result.confidence,
            symbols_mentioned=result.symbols_mentioned,
        )
        point_ids.append(point_id)
    return point_ids


def _score_one(item: NewsItem) -> _SentimentResult:
    system_prompt = get_active_prompt(PROMPT_SLUG)
    user_prompt = get_active_prompt(TASK_PROMPT_SLUG).format(
        title=item.title, summary=item.summary, source=item.source
    )
    response = complete(
        "sentiment",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    content = response.choices[0].message.content
    parsed = json.loads(extract_json(content))

    sentiment = str(parsed["sentiment"])
    if sentiment not in _VALID_SENTIMENTS:
        raise ValueError(f"LLM returned an unrecognized sentiment value: {sentiment!r}")

    return _SentimentResult(
        sentiment=sentiment,
        confidence=float(parsed["confidence"]),
        symbols_mentioned=[str(s) for s in parsed.get("symbols_mentioned", [])],
    )
