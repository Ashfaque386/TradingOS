"""CEO-led organisation layer tables (spec 001-ceo-led-trading-org, data-model.md §1-§6, §8).

System of record = Postgres (constitution principle V). Live event fan-out is Redis and
organisational memory is Qdrant -- neither is modelled here. Every non-terminal state
transition commits a row so a run can resume after a restart (FR-019) and replay from events
(FR-087).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, UUIDPKMixin


class OrganizationRun(Base, UUIDPKMixin):
    """data-model.md §1. One execution of the organisation against one objective."""

    __tablename__ = "organization_runs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_by: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    queue_position: Mapped[int | None] = mapped_column(Integer)
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizational_plans.id", use_alter=True)
    )
    thread_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    result_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    produced_strategy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id")
    )
    stall_flagged_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    ended_at: Mapped[datetime | None]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class OrganizationalPlan(Base, UUIDPKMixin):
    """data-model.md §2. The CEO's decomposition of an objective. One plan per run; a re-plan
    supersedes via a new plan row + `superseded_plan_id`."""

    __tablename__ = "organizational_plans"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization_runs.id"), nullable=False, unique=True
    )
    objective_classification: Mapped[str] = mapped_column(String(80), nullable=False)
    departments: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    constraints: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    safety_requirements: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    superseded_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizational_plans.id")
    )
    created_at: Mapped[datetime]


class Task(Base, UUIDPKMixin):
    """data-model.md §3 (fields per FR-010). A unit of delegated work assigned to one agent."""

    __tablename__ = "tasks"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizational_plans.id"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization_runs.id"), nullable=False
    )
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    assigned_agent: Mapped[str] = mapped_column(String(50), nullable=False)
    assigned_by: Mapped[str] = mapped_column(String(255), nullable=False)
    capability: Mapped[str] = mapped_column(String(80), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    dependency_policy: Mapped[str] = mapped_column(String(20), nullable=False, default="all")
    required_inputs: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    received_inputs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    required_datasets: Mapped[list[str] | None] = mapped_column(JSONB)
    expected_output: Mapped[str] = mapped_column(String(80), nullable=False)
    result_artefact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("result_artefacts.id", use_alter=True)
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="created")
    is_concurrency_safe: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    deadline: Mapped[datetime | None]
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id")
    )
    audit_reference: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("audit_log.id"))
    created_at: Mapped[datetime]
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    ran_concurrently: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dependency_wait_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TaskDependency(Base, UUIDPKMixin):
    """data-model.md §4. A directed 'dependent task requires an artefact owned by prerequisite
    task' edge. The full edge set per plan MUST be acyclic (checked at plan validation)."""

    __tablename__ = "task_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "dependent_task_id", "prerequisite_task_id", name="uq_task_dependency_pair"
        ),
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizational_plans.id"), nullable=False
    )
    dependent_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False
    )
    prerequisite_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False
    )
    required_artefact_type: Mapped[str] = mapped_column(String(80), nullable=False)
    policy: Mapped[str] = mapped_column(String(10), nullable=False, default="hard")
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="unsatisfied")
    satisfied_at: Mapped[datetime | None]
    created_at: Mapped[datetime]


class ResultArtefact(Base, UUIDPKMixin):
    """data-model.md §5 (FR-030/031). A typed output of an agent with provenance. Every artefact
    is either `consumed` by a downstream task or explicitly `informational` -- never orphaned."""

    __tablename__ = "result_artefacts"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization_runs.id"), nullable=False
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False
    )
    artefact_type: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    disposition: Mapped[str | None] = mapped_column(String(20))
    consumed_by_task_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    coverage: Mapped[str | None] = mapped_column(String(10))
    audit_reference: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("audit_log.id"))
    created_at: Mapped[datetime]


class OrganizationalDecision(Base, UUIDPKMixin):
    """data-model.md §6 (FR-022/023). A CEO-level decision, including conflict resolution and
    escalation. `summary` is an operational statement -- never private model chain-of-thought."""

    __tablename__ = "organizational_decisions"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization_runs.id"), nullable=False
    )
    decision_type: Mapped[str] = mapped_column(String(30), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_input_artefact_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    supporting_agents: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    next_step: Mapped[str | None] = mapped_column(Text)
    escalated_to_role: Mapped[str | None] = mapped_column(String(40))
    resolved_by: Mapped[str | None] = mapped_column(String(255))
    audit_reference: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("audit_log.id"))
    created_at: Mapped[datetime]


class OrganizationalEvent(Base):
    """data-model.md §8 (FR-140/141). Append-only record of a real state transition; the single
    source for both live console updates and run replay. `(run_id, sequence)` is gap-free per
    run. A DB trigger rejects UPDATE/DELETE (added in the migration, reusing the `audit_log`
    trigger pattern)."""

    __tablename__ = "organizational_events"
    __table_args__ = (UniqueConstraint("run_id", "sequence", name="uq_org_event_run_sequence"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization_runs.id"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime]
