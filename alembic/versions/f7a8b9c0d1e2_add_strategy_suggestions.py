"""add strategy_suggestions table (REL-048)

Revision ID: f7a8b9c0d1e2
Revises: 02166efcbb4f
Create Date: 2026-08-13 16:00:00.000000

New table backing the "suggest a change to this strategy, AI reviews and regenerates if sound"
feature (REL-048/049). A human writes free text against a real `Strategy` row; a lightweight
LLM review step (src/agents/nodes/suggestion_reviewer.py) judges it against the strategy's
current StrategyLogic + latest backtest verdict and, if sound, re-enters the real agent pipeline
(a new second compiled graph, build_suggestion_regeneration_graph() in src/agents/graph.py) to
produce a genuine new StrategyVersion + BacktestResult for a human to review -- not a
field-level edit and not merely a logged comment. `resulting_version_id` is only ever set once
`status` reaches `Applied`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: str | None = "02166efcbb4f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strategy_suggestions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submitted_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("suggestion_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="Pending"),
        sa.Column("ai_verdict", sa.Text(), nullable=True),
        sa.Column("ai_reasoning", sa.Text(), nullable=True),
        sa.Column("resulting_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('Pending', 'Reviewing', 'Rejected', 'Applied')", name="ck_suggestion_status"
        ),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategies.id"]),
        sa.ForeignKeyConstraint(["submitted_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["resulting_version_id"], ["strategy_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_strategy_suggestions_strategy_id", "strategy_suggestions", ["strategy_id"])


def downgrade() -> None:
    op.drop_index("ix_strategy_suggestions_strategy_id", table_name="strategy_suggestions")
    op.drop_table("strategy_suggestions")
