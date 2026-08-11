"""add option_legs and option_expiry columns to strategy_versions (REL-035)

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-08-11 00:00:00.000000

Closes a real gap the Paper Trading Account's daily signal job hit in production: the Options
Strategy Agent's chain-grounded option legs (strike/type/side/quantity, verified against a real
live option chain) previously existed only in the ephemeral LangGraph run's state, discarded the
moment that one graph run ended -- with nothing persisted, a standalone scheduled job running
days later had no way to recover what an F&O strategy is actually supposed to trade. Nullable,
not backfilled: a StrategyVersion row created before this migration never had real grounded legs
captured for it, recorded honestly as NULL, same convention as the trades/walk_forward_results
columns this migration mirrors (91d4a2939b4e, e7f8a9b0c1d2).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d6e7f8a9b0c1"
down_revision: str | None = "c5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("strategy_versions", sa.Column("option_legs", postgresql.JSONB(), nullable=True))
    op.add_column("strategy_versions", sa.Column("option_expiry", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("strategy_versions", "option_legs")
    op.drop_column("strategy_versions", "option_expiry")
