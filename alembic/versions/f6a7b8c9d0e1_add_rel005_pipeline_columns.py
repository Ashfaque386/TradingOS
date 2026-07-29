"""add REL-005 pipeline columns to backtest_results (evaluator/optimization/risk/deployment)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-25 15:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # REL-005 wires Evaluator/Optimization/RiskManager/Deployment agents into the graph --
    # Phase_11_Database_Design.md has no dedicated tables for their outputs, so (per the
    # roadmap-extension design decision) one backtest_results row is extended to carry the
    # whole downstream pipeline's outcome for that run, rather than inventing new tables.
    op.add_column(
        "backtest_results", sa.Column("evaluation_verdict", sa.String(length=10), nullable=True)
    )
    op.add_column(
        "backtest_results",
        sa.Column("evaluation_failure_reasons", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "backtest_results", sa.Column("optimization_best_params", postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        "backtest_results",
        sa.Column(
            "optimization_robustness_score", sa.Numeric(precision=6, scale=3), nullable=True
        ),
    )
    op.add_column(
        "backtest_results", sa.Column("risk_assessment_passed", sa.Boolean(), nullable=True)
    )
    op.add_column(
        "backtest_results", sa.Column("risk_assessment_notes", sa.Text(), nullable=True)
    )
    op.add_column(
        "backtest_results",
        sa.Column("deployment_recommendation", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "backtest_results", sa.Column("deployment_rationale", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("backtest_results", "deployment_rationale")
    op.drop_column("backtest_results", "deployment_recommendation")
    op.drop_column("backtest_results", "risk_assessment_notes")
    op.drop_column("backtest_results", "risk_assessment_passed")
    op.drop_column("backtest_results", "optimization_robustness_score")
    op.drop_column("backtest_results", "optimization_best_params")
    op.drop_column("backtest_results", "evaluation_failure_reasons")
    op.drop_column("backtest_results", "evaluation_verdict")
