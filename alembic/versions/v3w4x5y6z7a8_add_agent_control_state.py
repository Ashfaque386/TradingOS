"""add agent_control_state table (REL-019 E19.2, ADR 11)

Revision ID: v3w4x5y6z7a8
Revises: u2v3w4x5y6z7
Create Date: 2026-08-04 00:00:00.000000

ADR 11 (Phase_1_Architecture_Decision_Record.md) decided per-agent disable is a real, durable
admin toggle -- a halt-on-entry circuit breaker for the 11 LangGraph pipeline nodes, a real
skip-this-call check for independently-invoked agents. This table is the shared control-state
primitive both mechanisms read (src/agents/control.py). No row for a given `agent_name` means
enabled (fail-open default) -- only an explicit disable ever gets a row, so this table starts
empty and every agent starts enabled.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v3w4x5y6z7a8"
down_revision: Union[str, None] = "u2v3w4x5y6z7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_control_state",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_name", sa.String(length=50), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_name", name="uq_agent_control_state_agent_name"),
    )


def downgrade() -> None:
    op.drop_table("agent_control_state")
