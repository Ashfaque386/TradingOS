"""RAG ingestion helpers for the `trading_strategies` and `code_templates` Qdrant collections
(Phase 2 Epic E2.4, Phase_11_Database_Design.md §4 DB-023/DB-026).

Nothing calls `ingest_strategy_outcome` yet -- the Backtesting Agent that would produce real
BacktestMetrics is Phase 3 scope (Phase_14 REL-003). This module exists now so Phase 3's
Backtesting Agent has a ready-made, tested ingestion path to call the moment it lands, rather
than that agent needing to invent its own Qdrant write path.
"""

import uuid
from typing import Literal

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

from src.core.config import get_settings
from src.memory.embeddings import embed_text


def _client() -> QdrantClient:
    return QdrantClient(url=get_settings().qdrant_url)


def ingest_strategy_outcome(
    *,
    strategy_id: str,
    strategy_version_id: str,
    hypothesis: str,
    code: str,
    asset_class: str,
    sharpe_ratio: float,
    max_drawdown: float,
    status: Literal["active", "deprecated", "archived"],
    failure_reason: str | None = None,
) -> str:
    """Embeds a strategy's hypothesis+code+outcome and upserts it into `trading_strategies`,
    per the DB-023 payload schema. Returns the Qdrant point ID."""
    text = f"{hypothesis}\n\n{code}"
    vector = embed_text(text)
    point_id = str(uuid.uuid4())
    _client().upsert(
        collection_name="trading_strategies",
        points=[
            PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "strategy_id": strategy_id,
                    "strategy_version_id": strategy_version_id,
                    "asset_class": asset_class,
                    "sharpe_ratio": sharpe_ratio,
                    "max_drawdown": max_drawdown,
                    "status": status,
                    "failure_reason": failure_reason,
                },
            )
        ],
    )
    return point_id


def ingest_code_template(
    *, template_name: str, code: str, strategy_pattern: str, reuse_count: int = 0
) -> str:
    """Embeds an approved code template and upserts it into `code_templates`, per the DB-026
    payload schema. Returns the Qdrant point ID."""
    text = f"{strategy_pattern}\n\n{code}"
    vector = embed_text(text)
    point_id = str(uuid.uuid4())
    _client().upsert(
        collection_name="code_templates",
        points=[
            PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "template_name": template_name,
                    "strategy_pattern": strategy_pattern,
                    "reuse_count": reuse_count,
                },
            )
        ],
    )
    return point_id
