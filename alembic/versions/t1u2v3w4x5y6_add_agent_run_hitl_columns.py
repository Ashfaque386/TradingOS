"""add human_decision + retried_from_run_id to agent_runs (REL-010 E10.8d)

Revision ID: t1u2v3w4x5y6
Revises: n5o6p7q8r9s0
Create Date: 2026-07-31 00:00:00.000000

Backs the Orchestrator HITL surface (POST /agents/runs/{id}/retry|approve|reject):
`human_decision` records a human's Approved/Rejected sign-off on a run's deployment
recommendation; `retried_from_run_id` links a fresh root AgentRun back to the Failed run a
human asked to retry, a self-referential FK on the same table as `parent_run_id`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "t1u2v3w4x5y6"
down_revision: Union[str, None] = "n5o6p7q8r9s0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_runs", sa.Column("human_decision", sa.String(length=20), nullable=True)
    )
    op.create_check_constraint(
        "ck_agent_runs_human_decision",
        "agent_runs",
        "human_decision IN ('Approved', 'Rejected')",
    )
    op.add_column(
        "agent_runs",
        sa.Column("retried_from_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_runs_retried_from_run_id",
        "agent_runs",
        "agent_runs",
        ["retried_from_run_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_agent_runs_retried_from_run_id", "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "retried_from_run_id")
    op.drop_constraint("ck_agent_runs_human_decision", "agent_runs", type_="check")
    op.drop_column("agent_runs", "human_decision")
