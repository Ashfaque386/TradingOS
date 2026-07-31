"""RAG ingestion for the `news_sentiment` Qdrant collection (REL-010 E10.3, Phase_11 §4 DB-025)
-- the collection was reserved in src/memory/collections.py's COLLECTIONS list since Phase 2 but
never written to until now. Mirrors src/memory/strategy_memory.py::ingest_strategy_outcome's
exact embed+upsert pattern.
"""

import uuid
from datetime import datetime
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

from src.core.config import get_settings
from src.memory.embeddings import embed_text

_COLLECTION = "news_sentiment"


def _client() -> QdrantClient:
    return QdrantClient(url=get_settings().qdrant_url)


def ingest_news_sentiment(
    *,
    title: str,
    summary: str,
    source: str,
    url: str,
    published_at: datetime | None,
    sentiment: str,
    confidence: float,
    symbols_mentioned: list[str],
) -> str:
    """Embeds a news item's title+summary and upserts it into `news_sentiment` alongside the
    Sentiment Agent's real scoring output. Returns the Qdrant point ID."""
    text = f"{title}\n\n{summary}"
    vector = embed_text(text)
    point_id = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "title": title,
        "summary": summary,
        "source": source,
        "url": url,
        "published_at": published_at.isoformat() if published_at else None,
        "sentiment": sentiment,
        "confidence": confidence,
        "symbols_mentioned": symbols_mentioned,
    }
    _client().upsert(
        collection_name=_COLLECTION,
        points=[PointStruct(id=point_id, vector=vector, payload=payload)],
    )
    return point_id
