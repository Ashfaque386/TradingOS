"""REL-060 (API-020/021): a real LangGraph checkpointer for `build_graph()` (src/agents/graph.py),
Postgres-backed so a paused run's exact execution position survives an app/container restart --
`langgraph.checkpoint.postgres.PostgresSaver`, confirmed via a real, throwaway probe script run
against this project's own dev Postgres before writing any of this: pausing after one node,
reopening a fresh connection, and resuming correctly ran only the remaining nodes (not re-running
the first one), and the checkpointer's own tables -- created once via the schema-owning
`tradingos` role (see alembic/versions of this release) -- were immediately readable/writable by
the low-privilege runtime `tradingos_app` role with zero extra GRANTs, thanks to the
`ALTER DEFAULT PRIVILEGES` rule REL-014's own migration (u2v3w4x5y6z7) already put in place.

`PostgresSaver.from_conn_string()` is a context manager, not a persistent object -- opened fresh
for the lifetime of one graph run (pause or resume), matching this codebase's own established
per-use-connection convention (`get_session()`, `get_redis_client()`) rather than a long-lived
global connection.
"""

from src.core.config import get_settings


def runtime_checkpoint_dsn() -> str:
    """The real runtime DB connection (the low-privilege `tradingos_app` role in every real
    deployment of this app, per docker-compose.yml's `DATABASE_URL`) -- `PostgresSaver` needs a
    plain psycopg-style DSN, not SQLAlchemy's `+psycopg` dialect suffix."""
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://", 1)
