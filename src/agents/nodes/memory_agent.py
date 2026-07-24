"""Memory Agent v1 (AGT-009, PMPT-009) — Phase 2 Epic E2.4.

Per Phase_4_AI_Agent_Design.md §9, this agent "runs asynchronously every weekend" -- no
scheduler exists yet (Temporal is deferred; see Phase_14 REL-002 E2.2 notes), so these are
plain callables a future scheduled job will invoke, not a LangGraph node wired into the main
research graph. "Never delete critical historical knowledge without archival" (§9): low-
confidence memories are marked `status="archived"` in place, never hard-deleted.
"""

from typing import Any

from qdrant_client import QdrantClient

from src.agents.llm_router import complete
from src.agents.prompt_registry import get_active_prompt
from src.core.config import get_settings

PROMPT_SLUG = "memory_agent"
TASK_PROMPT_SLUG = "memory_agent_task"


def _client() -> QdrantClient:
    return QdrantClient(url=get_settings().qdrant_url)


def archive_low_confidence_memories(
    collection_name: str = "trading_strategies", sharpe_threshold: float = 0.5
) -> list[str]:
    """Marks points with sharpe_ratio below the threshold as archived (never hard-deleted).
    Returns the list of point IDs archived."""
    client = _client()
    archived_ids: list[str] = []
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection_name, limit=100, offset=offset, with_payload=True
        )
        for point in points:
            payload = point.payload or {}
            sharpe = payload.get("sharpe_ratio")
            if (
                sharpe is not None
                and sharpe < sharpe_threshold
                and payload.get("status") != "archived"
            ):
                client.set_payload(
                    collection_name=collection_name,
                    payload={"status": "archived"},
                    points=[point.id],
                )
                archived_ids.append(str(point.id))
        if offset is None:
            break
    return archived_ids


def generate_lessons_learned_summary(collection_name: str = "trading_strategies") -> str:
    """Summarizes recurring success/failure patterns across all stored strategy outcomes."""
    client = _client()
    points, _ = client.scroll(collection_name=collection_name, limit=200, with_payload=True)
    payloads: list[dict[str, Any]] = [p.payload for p in points if p.payload]

    system_prompt = get_active_prompt(PROMPT_SLUG)
    user_prompt = get_active_prompt(TASK_PROMPT_SLUG).format(count=len(payloads), payloads=payloads)
    response = complete(
        "research",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    content: str = response.choices[0].message.content
    return content
