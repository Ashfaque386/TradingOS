"""add scheduled_job_config and scheduled_job_run tables (REL-081)

Revision ID: 1b01846d61e6
Revises: c0d1e2f3a4b5
Create Date: 2026-09-01 06:48:32.598696

Replaces the 4 real Windows Scheduled Tasks (Shadow Mode, Audit Archive, Audit Chain
Verification, Data Lake Backup) -- confirmed unreliable this session (`Get-ScheduledTaskInfo`
showed real launch/kill failures on all 4, `LogonType=Interactive` only firing within an active
desktop session) -- with a real in-process apscheduler job for each, driven by these two tables.

`scheduled_job_config` (DB-040) is the runtime-editable schedule override, fail-open: no row for
a `job_id` means "use the hardcoded default cron + enabled", the same no-row-means-default
convention `agent_control_state` already established -- shipping this migration changes nothing
about when any job actually fires until an admin explicitly edits one.

`scheduled_job_run` (DB-041) is the real execution-history ledger, one row per real firing (cron
or manual "Run Now") of any of the 11 real scheduled jobs (7 pre-existing + these 4).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "1b01846d61e6"
down_revision: str | None = "c0d1e2f3a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduled_job_config",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", sa.String(length=100), nullable=False),
        sa.Column("cron_expression", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_scheduled_job_config_job_id"),
    )
    op.create_table(
        "scheduled_job_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", sa.String(length=100), nullable=False),
        sa.Column("trigger_source", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="Running"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("triggered_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["triggered_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scheduled_job_run_job_id_started_at",
        "scheduled_job_run",
        ["job_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_scheduled_job_run_job_id_started_at", table_name="scheduled_job_run")
    op.drop_table("scheduled_job_run")
    op.drop_table("scheduled_job_config")
