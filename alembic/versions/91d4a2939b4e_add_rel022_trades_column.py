"""add REL-022 trades column to backtest_results (real per-trade ledger, PMPT-004 v3)

Revision ID: 91d4a2939b4e
Revises: v3w4x5y6z7a8
Create Date: 2026-08-05 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "91d4a2939b4e"
down_revision: Union[str, None] = "v3w4x5y6z7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # REL-022: the sandboxed strategy code's return contract (PMPT-004 v3) now includes a real
    # per-trade ledger -- previously discarded entirely (only aggregate metrics/equity curve were
    # captured). Nullable, not backfilled: a row created under the v2 contract genuinely has no
    # trade ledger to store, and that's recorded honestly as NULL rather than an empty list
    # implying "zero real trades occurred."
    op.add_column(
        "backtest_results", sa.Column("trades", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("backtest_results", "trades")
