"""add strategy_versions.agent_run_id (API-007/008 session-scoped Live Canvas artifacts)

Revision ID: 2fc35def329f
Revises: 1b01846d61e6
Create Date: 2026-09-05 18:15:00.000000

The one Live Canvas artifact type (code) that had no durable link back to the AgentRun/
graph_thread_id that produced it -- BacktestResult.agent_run_id and AgentLog.agent_run_id both
already existed. Nullable, not backfilled: a StrategyVersion row created before this migration
genuinely has no real run to attribute it to, same honest-None convention already used elsewhere
on this table (option_legs/option_expiry/option_rationale).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "2fc35def329f"
down_revision: str | None = "1b01846d61e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "strategy_versions",
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_strategy_versions_agent_run_id",
        "strategy_versions",
        "agent_runs",
        ["agent_run_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_strategy_versions_agent_run_id", "strategy_versions", type_="foreignkey"
    )
    op.drop_column("strategy_versions", "agent_run_id")
