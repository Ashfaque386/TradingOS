"""add pause/resume columns to agent_runs + real LangGraph checkpointer tables (REL-060, API-020/021)

Revision ID: a1a5d7f7bb58
Revises: f7a8b9c0d1e2
Create Date: 2026-08-14 00:00:00.000000

API-020/021 (pause/resume a running graph execution) were confirmed genuinely missing during
REL-059's full API audit for a real, deeper reason, not just an unwired route: `build_graph()`
(src/agents/graph.py) never attached a LangGraph checkpointer, so `graph.stream()` kept no
execution-position state at all -- there was no persisted point to pause at or resume from.

Two `agent_runs` columns close the REST-facing half of the gap: `pause_requested` is the real,
DB-backed signal `POST /agents/runs/{id}/pause` sets, checked by the running background thread
between graph steps (the only safe interruption point -- a node can't be stopped mid-execution
without risking a half-written Strategy/BacktestResult row); `tracking_snapshot` persists
`_StrategyTracking`'s local bookkeeping (src/api/routers/agents.py) across the pause boundary,
since that dataclass lives outside `TradingOSGraphState` and would otherwise be lost when the
background thread's function returns.

The `checkpoints`/`checkpoint_blobs`/`checkpoint_writes`/`checkpoint_migrations` tables below are
NOT Alembic-modeled tables -- they're created by calling `langgraph.checkpoint.postgres.
PostgresSaver.setup()` directly, the library's own documented one-time setup call, run here (via
the schema-owning `tradingos` role this migration already runs as) rather than at app startup, so
schema changes stay a single, deliberate, human-triggered operation like every other migration in
this project. This was verified end-to-end against this project's own dev Postgres before being
written here (a real pause after one node, a fresh connection, and a correct resume that re-ran
only the remaining nodes) -- confirming setup() run as `tradingos` needs zero followup GRANTs
for the low-privilege runtime `tradingos_app` role to read/write these tables during real graph
runs: `u2v3w4x5y6z7`'s own `ALTER DEFAULT PRIVILEGES FOR ROLE tradingos ... GRANT ... TO
tradingos_app` rule already covers any future table `tradingos` creates, these included.
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a1a5d7f7bb58"
down_revision: str | None = "f7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Same fallback chain alembic/env.py itself already uses for the migration connection -- this
# migration needs its own separate raw psycopg connection (PostgresSaver's own API, not
# SQLAlchemy) rather than reusing Alembic's `op.get_bind()`, so it re-derives the DSN the same
# way rather than importing `src.core.config` (no migration in this project imports app code).
_MIGRATION_DSN = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://tradingos:tradingos_dev_password@postgres:5432/tradingos"
)


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("pause_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "agent_runs", sa.Column("tracking_snapshot", postgresql.JSONB(), nullable=True)
    )

    from langgraph.checkpoint.postgres import PostgresSaver

    psycopg_dsn = _MIGRATION_DSN.replace("postgresql+psycopg://", "postgresql://", 1)
    with PostgresSaver.from_conn_string(psycopg_dsn) as saver:
        saver.setup()


def downgrade() -> None:
    op.drop_column("agent_runs", "tracking_snapshot")
    op.drop_column("agent_runs", "pause_requested")
    # The checkpoint tables are deliberately NOT dropped here -- PostgresSaver.setup() is
    # idempotent (CREATE TABLE IF NOT EXISTS-style) and re-running `upgrade()` later is safe;
    # dropping real, possibly-in-use checkpoint data as a side effect of an unrelated downgrade
    # would be a real, surprising data-loss risk this migration would rather not introduce.
