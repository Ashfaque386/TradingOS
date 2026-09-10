"""orchestration_core -- CEO-led organisation layer tables (spec 001-ceo-led-trading-org, T010).

Creates the 11 new tables from data-model.md (organization_runs, organizational_plans, tasks,
task_dependencies, result_artefacts, organizational_decisions, organizational_events,
approval_requests, agent_configs, prompt_versions, dataset_freshness_records), a partial unique
index enforcing "at most one active prompt version per (agent_slug, kind)", and a BEFORE
UPDATE OR DELETE trigger making `organizational_events` append-only (reusing the `audit_log`
trigger pattern) plus REVOKE UPDATE/DELETE from `tradingos_app`.

Note: `strategies.status` has no CHECK constraint in this schema (verified against the live DB),
so the new `PendingPaperApproval` value needs no constraint change -- "PendingPaperApproval" is
20 chars and fits the existing String(20) column.

Hand-written from the autogenerate output: the raw autogenerate also wanted to drop LangGraph's
externally-managed checkpoint tables and several unrelated tables/indexes -- all discarded.

Revision ID: eb7e9528f695
Revises: 1234045ffcf9
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "eb7e9528f695"
down_revision: str | None = "1234045ffcf9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSONB = postgresql.JSONB(astext_type=sa.Text())

_APPEND_ONLY_FN = """
CREATE OR REPLACE FUNCTION reject_organizational_events_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'organizational_events is append-only (spec FR-140)';
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.create_table(
        "agent_configs",
        sa.Column("agent_slug", sa.String(length=50), nullable=False),
        sa.Column("is_llm_backed", sa.Boolean(), nullable=False),
        sa.Column("provider_model_mode", sa.String(length=10), nullable=True),
        sa.Column("custom_provider", sa.String(length=40), nullable=True),
        sa.Column("custom_model", sa.String(length=120), nullable=True),
        sa.Column("active_system_prompt_version_id", sa.UUID(), nullable=True),
        sa.Column("active_task_prompt_version_id", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["active_system_prompt_version_id"],
            ["prompt_versions.id"],
            name="fk_agent_configs_system_prompt",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(
            ["active_task_prompt_version_id"],
            ["prompt_versions.id"],
            name="fk_agent_configs_task_prompt",
            use_alter=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_slug"),
    )
    op.create_table(
        "dataset_freshness_records",
        sa.Column("dataset_name", sa.String(length=60), nullable=False),
        sa.Column("cadence", sa.String(length=60), nullable=False),
        sa.Column("freshness_rule", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("last_successful_update", sa.DateTime(), nullable=True),
        sa.Column("last_checksum_ok", sa.Boolean(), nullable=True),
        sa.Column("retry_state", _JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_name"),
    )
    op.create_table(
        "prompt_versions",
        sa.Column("agent_slug", sa.String(length=50), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("author", sa.String(length=255), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_slug", "kind", "version", name="uq_prompt_version_triple"),
    )
    op.create_index(
        "uq_prompt_version_one_active",
        "prompt_versions",
        ["agent_slug", "kind"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "organization_runs",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("queue_position", sa.Integer(), nullable=True),
        sa.Column("plan_id", sa.UUID(), nullable=True),
        sa.Column("thread_id", sa.String(length=100), nullable=False),
        sa.Column("result_summary", _JSONB, nullable=True),
        sa.Column("produced_strategy_id", sa.UUID(), nullable=True),
        sa.Column("stall_flagged_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["organizational_plans.id"],
            name="fk_organization_runs_plan_id",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(["produced_strategy_id"], ["strategies.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("thread_id"),
    )
    op.create_table(
        "organizational_plans",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("objective_classification", sa.String(length=80), nullable=False),
        sa.Column("departments", _JSONB, nullable=False),
        sa.Column("constraints", _JSONB, nullable=False),
        sa.Column("safety_requirements", _JSONB, nullable=False),
        sa.Column("approval_required", sa.Boolean(), nullable=False),
        sa.Column("superseded_plan_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["organization_runs.id"]),
        sa.ForeignKeyConstraint(["superseded_plan_id"], ["organizational_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_table(
        "tasks",
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("parent_task_id", sa.UUID(), nullable=True),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("assigned_agent", sa.String(length=50), nullable=False),
        sa.Column("assigned_by", sa.String(length=255), nullable=False),
        sa.Column("capability", sa.String(length=80), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("dependency_policy", sa.String(length=20), nullable=False),
        sa.Column("required_inputs", _JSONB, nullable=False),
        sa.Column("received_inputs", _JSONB, nullable=False),
        sa.Column("required_datasets", _JSONB, nullable=True),
        sa.Column("expected_output", sa.String(length=80), nullable=False),
        sa.Column("result_artefact_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("is_concurrency_safe", sa.Boolean(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("deadline", sa.DateTime(), nullable=True),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(length=100), nullable=False),
        sa.Column("agent_run_id", sa.UUID(), nullable=True),
        sa.Column("audit_reference", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("ran_concurrently", sa.Boolean(), nullable=False),
        sa.Column("dependency_wait_seconds", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"]),
        sa.ForeignKeyConstraint(["audit_reference"], ["audit_log.id"]),
        sa.ForeignKeyConstraint(["parent_task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["organizational_plans.id"]),
        sa.ForeignKeyConstraint(
            ["result_artefact_id"],
            ["result_artefacts.id"],
            name="fk_tasks_result_artefact_id",
            use_alter=True,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["organization_runs.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasks_run_id_status", "tasks", ["run_id", "status"])
    op.create_table(
        "result_artefacts",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("artefact_type", sa.String(length=80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", _JSONB, nullable=False),
        sa.Column("provenance", _JSONB, nullable=False),
        sa.Column("disposition", sa.String(length=20), nullable=True),
        sa.Column("consumed_by_task_ids", _JSONB, nullable=False),
        sa.Column("coverage", sa.String(length=10), nullable=True),
        sa.Column("audit_reference", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["audit_reference"], ["audit_log.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["organization_runs.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "task_dependencies",
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("dependent_task_id", sa.UUID(), nullable=False),
        sa.Column("prerequisite_task_id", sa.UUID(), nullable=False),
        sa.Column("required_artefact_type", sa.String(length=80), nullable=False),
        sa.Column("policy", sa.String(length=10), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("satisfied_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["dependent_task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["organizational_plans.id"]),
        sa.ForeignKeyConstraint(["prerequisite_task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dependent_task_id", "prerequisite_task_id", name="uq_task_dependency_pair"
        ),
    )
    op.create_table(
        "organizational_decisions",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("decision_type", sa.String(length=30), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("supporting_input_artefact_ids", _JSONB, nullable=False),
        sa.Column("supporting_agents", _JSONB, nullable=False),
        sa.Column("next_step", sa.Text(), nullable=True),
        sa.Column("escalated_to_role", sa.String(length=40), nullable=True),
        sa.Column("resolved_by", sa.String(length=255), nullable=True),
        sa.Column("audit_reference", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["audit_reference"], ["audit_log.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["organization_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "organizational_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("subject_type", sa.String(length=20), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column("payload", _JSONB, nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["organization_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_org_event_run_sequence"),
    )
    op.create_table(
        "approval_requests",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("strategy_id", sa.UUID(), nullable=False),
        sa.Column("strategy_version_id", sa.UUID(), nullable=True),
        sa.Column("recommendation_artefact_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("decided_by", sa.String(length=255), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("audit_reference", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["audit_reference"], ["audit_log.id"]),
        sa.ForeignKeyConstraint(["recommendation_artefact_id"], ["result_artefacts.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["organization_runs.id"]),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategies.id"]),
        sa.ForeignKeyConstraint(["strategy_version_id"], ["strategy_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Append-only trigger on organizational_events (FR-140) + defence-in-depth REVOKE.
    op.execute(_APPEND_ONLY_FN)
    op.execute(
        "CREATE TRIGGER trg_organizational_events_append_only "
        "BEFORE UPDATE OR DELETE ON organizational_events "
        "FOR EACH ROW EXECUTE FUNCTION reject_organizational_events_mutation()"
    )
    op.execute("REVOKE UPDATE, DELETE ON organizational_events FROM tradingos_app")


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_organizational_events_append_only " "ON organizational_events"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_organizational_events_mutation()")
    op.execute(
        "ALTER TABLE organization_runs DROP CONSTRAINT IF EXISTS fk_organization_runs_plan_id"
    )
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS fk_tasks_result_artefact_id")
    op.drop_table("approval_requests")
    op.drop_table("organizational_events")
    op.drop_table("organizational_decisions")
    op.drop_table("task_dependencies")
    op.drop_table("result_artefacts")
    op.drop_index("ix_tasks_run_id_status", table_name="tasks")
    op.drop_table("tasks")
    op.drop_table("organizational_plans")
    op.drop_table("organization_runs")
    op.drop_index("uq_prompt_version_one_active", table_name="prompt_versions")
    op.drop_table("prompt_versions")
    op.drop_table("dataset_freshness_records")
    op.drop_table("agent_configs")
