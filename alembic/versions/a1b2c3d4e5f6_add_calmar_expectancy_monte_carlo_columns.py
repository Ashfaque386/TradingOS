"""add calmar_ratio, expectancy, monte_carlo_p95_max_drawdown to backtest_results

Revision ID: a1b2c3d4e5f6
Revises: 6cd568130517
Create Date: 2026-07-22 22:55:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "6cd568130517"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "backtest_results",
        sa.Column("calmar_ratio", sa.Numeric(precision=8, scale=3), nullable=True),
    )
    op.add_column(
        "backtest_results",
        sa.Column("expectancy", sa.Numeric(precision=14, scale=2), nullable=True),
    )
    op.add_column(
        "backtest_results",
        sa.Column(
            "monte_carlo_p95_max_drawdown", sa.Numeric(precision=6, scale=3), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("backtest_results", "monte_carlo_p95_max_drawdown")
    op.drop_column("backtest_results", "expectancy")
    op.drop_column("backtest_results", "calmar_ratio")
