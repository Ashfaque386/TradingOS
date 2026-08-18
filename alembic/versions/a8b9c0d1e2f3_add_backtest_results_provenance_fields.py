"""add backtest_results.provider_used/data_retrieved_at (REL-073, Phase 4 of the Upstox V3 +
yfinance dual market-data system)

Revision ID: a8b9c0d1e2f3
Revises: z7a8b9c0d1e2
Create Date: 2026-08-18 00:00:00.000000

Real reproducibility provenance -- which provider's data a backtest actually ran against, and
when that data was last fetched, sourced from the new market_data_provenance table. Nullable,
not backfilled -- a row created before this migration has no real provenance to recover, same
honest convention as data_adjusted (REL-072).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, None] = "z7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("backtest_results", sa.Column("provider_used", sa.String(length=20), nullable=True))
    op.add_column(
        "backtest_results", sa.Column("data_retrieved_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("backtest_results", "data_retrieved_at")
    op.drop_column("backtest_results", "provider_used")
