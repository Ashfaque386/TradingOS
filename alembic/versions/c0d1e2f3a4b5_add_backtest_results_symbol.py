"""add backtest_results.symbol (REL-075, one-off symbol override at backtest-trigger time)

Revision ID: c0d1e2f3a4b5
Revises: a8b9c0d1e2f3
Create Date: 2026-08-18 00:00:00.000000

The real symbol a given backtest run actually used -- always implicitly
strategy.universe[0] before a one-off trigger-time override became possible, so a row created
before this migration genuinely never recorded it. Nullable, not backfilled -- same honest
convention as data_adjusted/provider_used/data_retrieved_at/initial_capital before it.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("backtest_results", sa.Column("symbol", sa.String(length=30), nullable=True))


def downgrade() -> None:
    op.drop_column("backtest_results", "symbol")
