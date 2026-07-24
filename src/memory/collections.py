"""Bootstraps the Qdrant collections defined in Phase_11_Database_Design.md (DB-023..DB-026).

Vector size comes from src/memory/embeddings.py's get_embedding_dim(), which depends on the
EMBEDDING_PROVIDER setting -- changing that setting means re-running bootstrap_collections
with recreate_if_dim_mismatch=True.
"""

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from src.memory.embeddings import get_embedding_dim

COLLECTIONS = ["trading_strategies", "agent_memory", "news_sentiment", "code_templates"]


def bootstrap_collections(
    client: QdrantClient, *, recreate_if_dim_mismatch: bool = False
) -> list[str]:
    """Idempotently creates any missing collections from COLLECTIONS; returns names created.

    If `recreate_if_dim_mismatch` is set, an existing collection whose vector size no longer
    matches the configured embedding provider's dimension is dropped and recreated (safe only
    while it holds no data you need -- Qdrant has no in-place resize)."""
    dim = get_embedding_dim()
    existing = {c.name for c in client.get_collections().collections}
    created = []
    for name in COLLECTIONS:
        if name in existing:
            if recreate_if_dim_mismatch and _needs_recreate(client, name, dim):
                client.delete_collection(name)
            else:
                continue
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        created.append(name)
    return created


def _needs_recreate(client: QdrantClient, name: str, expected_dim: int) -> bool:
    info = client.get_collection(name)
    current_size = info.config.params.vectors.size  # type: ignore[union-attr]
    return current_size != expected_dim


def main() -> None:
    from src.core.config import get_settings

    client = QdrantClient(url=get_settings().qdrant_url)
    created = bootstrap_collections(client, recreate_if_dim_mismatch=True)
    print(f"Created collections: {created}" if created else "All collections already exist.")


if __name__ == "__main__":
    main()
