"""add backtest_results.data_adjusted (REL-072, Phase 3 of the Upstox V3 + yfinance dual
market-data system)

Revision ID: y6z7a8b9c0d1
Revises: x5y6z7a8b9c0
Create Date: 2026-08-18 00:00:00.000000

Closes the corporate-actions gap this release found: `run_real_backtest()` (the function every
real backtest actually goes through) never applied split/bonus adjustment, even though the real,
tested pipeline in src/engine/backtest/corporate_actions_adjust.py has existed since REL-010.
Nullable, not backfilled -- a row created before this migration genuinely never had real
adjustment applied (the bug this release fixes), so NULL is the honest value for it, not a
fabricated true/false.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "y6z7a8b9c0d1"
down_revision: Union[str, None] = "x5y6z7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("backtest_results", sa.Column("data_adjusted", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("backtest_results", "data_adjusted")
