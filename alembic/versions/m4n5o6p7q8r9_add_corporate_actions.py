"""add corporate_actions table (REL-010 E10.7, DB-021)

Revision ID: m4n5o6p7q8r9
Revises: l3m4n5o6p7q8
Create Date: 2026-07-31 00:00:00.000000

DB-021 CORPORATE_ACTIONS had zero code prior to this migration -- backtests read raw
DataLake.read_symbol() output with no split/dividend adjustment, a real correctness gap
(src/engine/backtest/data_feed.py, fixed alongside this migration via
src/engine/backtest/corporate_actions_adjust.py). See src/models/corporate_action.py's own
docstring for the ratio/dividend column semantics.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "m4n5o6p7q8r9"
down_revision: Union[str, None] = "l3m4n5o6p7q8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "corporate_actions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("ex_date", sa.Date(), nullable=False),
        sa.Column("action_type", sa.String(length=20), nullable=False),
        sa.Column("ratio_numerator", sa.Numeric(10, 4), nullable=True),
        sa.Column("ratio_denominator", sa.Numeric(10, 4), nullable=True),
        sa.Column("dividend_amount", sa.Numeric(12, 4), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("action_type IN ('SPLIT', 'BONUS', 'DIVIDEND')", name="ck_action_type"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "ex_date", "action_type"),
    )
    op.create_index("ix_corporate_actions_symbol", "corporate_actions", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_corporate_actions_symbol", table_name="corporate_actions")
    op.drop_table("corporate_actions")
