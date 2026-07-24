"""add universe to strategies

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-07-24 06:50:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # StrategyLogic.universe (src/agents/state.py) was never persisted anywhere -- Phase 4
    # Epic E4.3's real backtest trigger (src/engine/sandbox/backtest_runner.py) needs to know
    # which symbol(s) a strategy targets to load real historical data for it.
    op.add_column(
        "strategies",
        sa.Column("universe", postgresql.ARRAY(sa.String(length=30)), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("strategies", "universe")
