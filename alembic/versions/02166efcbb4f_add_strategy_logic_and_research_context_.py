"""add strategy logic and research context columns (REL-044)

Revision ID: 02166efcbb4f
Revises: d6e7f8a9b0c1
Create Date: 2026-08-13 13:17:22.802609

Closes a real gap found while investigating a user report that the Strategies page shows "No
hypothesis recorded." with no other detail: the Strategy Generator Agent (AGT-003) computes a
full StrategyLogic object on every run (src/agents/state.py) -- entry_conditions, exit_conditions,
stop_loss, take_profit, position_sizing, confidence_score alongside the already-persisted
hypothesis/asset_class/style/universe -- but until this migration those six fields had no column
to be written to at all, and were silently discarded in
src/api/routers/agents.py::_persist_strategy_progress. Also adds research_context/market_context
(the CEO Agent's ResearchDirective and Market Analyst's MarketContext that led to this strategy
being proposed -- real "why" context, previously only transient in AgentRun.output_state) and
StrategyVersion.option_rationale (the Options Strategy Agent's rationale for its F&O legs,
computed but discarded before reaching TradingOSGraphState). All nullable, none backfilled: a row
created before this migration has no real data to recover, same convention as option_legs/
option_expiry (d6e7f8a9b0c1) and every other honestly-null column in this schema.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "02166efcbb4f"
down_revision: str | None = "d6e7f8a9b0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("strategies", sa.Column("entry_conditions", sa.Text(), nullable=True))
    op.add_column("strategies", sa.Column("exit_conditions", sa.Text(), nullable=True))
    op.add_column("strategies", sa.Column("stop_loss", sa.Text(), nullable=True))
    op.add_column("strategies", sa.Column("take_profit", sa.Text(), nullable=True))
    op.add_column("strategies", sa.Column("position_sizing", sa.Text(), nullable=True))
    op.add_column("strategies", sa.Column("confidence_score", sa.Numeric(6, 3), nullable=True))
    op.add_column("strategies", sa.Column("research_context", postgresql.JSONB(), nullable=True))
    op.add_column("strategies", sa.Column("market_context", postgresql.JSONB(), nullable=True))
    op.add_column("strategy_versions", sa.Column("option_rationale", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("strategy_versions", "option_rationale")
    op.drop_column("strategies", "market_context")
    op.drop_column("strategies", "research_context")
    op.drop_column("strategies", "confidence_score")
    op.drop_column("strategies", "position_sizing")
    op.drop_column("strategies", "take_profit")
    op.drop_column("strategies", "stop_loss")
    op.drop_column("strategies", "exit_conditions")
    op.drop_column("strategies", "entry_conditions")
