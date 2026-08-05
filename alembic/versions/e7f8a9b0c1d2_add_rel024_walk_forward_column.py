"""add REL-024 walk_forward_results column to backtest_results (real Walk-Forward Optimization)

Revision ID: e7f8a9b0c1d2
Revises: 91d4a2939b4e
Create Date: 2026-08-05 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "91d4a2939b4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # REL-024: real Walk-Forward Optimization window summaries, wired into both the direct-API
    # backtest path and the LangGraph optimization_node -- previously no adapter existed from the
    # LLM-generated sandboxed strategy code to walk_forward.py's StrategyFn contract at all, so
    # nothing was ever computed to store here. Nullable, not backfilled: a row created before this
    # migration (or a real run with too little history for even one rolling window) has no real
    # windows to store, recorded honestly as NULL.
    op.add_column(
        "backtest_results", sa.Column("walk_forward_results", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("backtest_results", "walk_forward_results")
