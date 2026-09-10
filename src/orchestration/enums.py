"""Status enums for the organisation layer (spec T005 / FR-011 / FR-012 / data-model.md §16).

Four *distinct* concepts, never conflated (spec FR-012, audit BUG-I): a Task's status, an
organisation Run's status, an Agent's derived status, and an Approval's status. Each is a plain
`str` enum so the value stores directly in a Postgres column and mirrors as a CHECK constraint
(matching the `ml_models.model_type` precedent).
"""

from __future__ import annotations

from enum import StrEnum


class RunStatus(StrEnum):
    """`OrganizationRun.status` (data-model.md §1)."""

    QUEUED = "queued"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    STALLED = "stalled"
    COMPLETED = "completed"
    FAILED = "failed"
    CANNOT_PLAN = "cannot_plan"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    """`Task.status` (data-model.md §3, FR-011). 15 values."""

    CREATED = "created"
    PLANNED = "planned"
    QUEUED = "queued"
    READY = "ready"
    RUNNING = "running"
    WAITING_FOR_DEPENDENCY = "waiting_for_dependency"
    WAITING_FOR_AGENT = "waiting_for_agent"
    BLOCKED = "blocked"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    ESCALATED = "escalated"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class AgentStatus(StrEnum):
    """Derived per-agent status for the console (data-model.md §16) -- computed from recent
    `AgentRun` outcomes + control state, never stored per run."""

    IDLE = "idle"
    RUNNING = "running"
    ESCALATED = "escalated"
    DISABLED = "disabled"
    DEGRADED = "degraded"


class ApprovalStatus(StrEnum):
    """`ApprovalRequest.status` (data-model.md §7, FR-052)."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DependencyState(StrEnum):
    """`TaskDependency.state` (data-model.md §4)."""

    UNSATISFIED = "unsatisfied"
    SATISFIED = "satisfied"
    FAILED = "failed"


class DependencyPolicy(StrEnum):
    """`Task.dependency_policy` (FR-010) / `TaskDependency.policy` (data-model.md §4)."""

    ALL = "all"
    ANY = "any"
    BEST_EFFORT = "best_effort"


class ArtefactDisposition(StrEnum):
    """`ResultArtefact.disposition` (FR-031). Every artefact is one or the other."""

    CONSUMED = "consumed"
    INFORMATIONAL = "informational"


class ArtefactCoverage(StrEnum):
    """`ResultArtefact.coverage` (FR-044) -- set on assembled context artefacts."""

    FULL = "full"
    REDUCED = "reduced"


class RunSource(StrEnum):
    """`OrganizationRun.source` (FR-001, FR-132)."""

    WEB = "web"
    SCHEDULE = "schedule"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    SLACK = "slack"
    API = "api"


class DecisionType(StrEnum):
    """`OrganizationalDecision.decision_type` (data-model.md §6)."""

    PROCEED = "proceed"
    REQUEST_REVIEW = "request_review"
    RESOLVE_CONFLICT = "resolve_conflict"
    CHOOSE_FALLBACK = "choose_fallback"
    REASSIGN = "reassign"
    ESCALATE_HUMAN = "escalate_human"
    CANNOT_PLAN = "cannot_plan"
    RE_PLAN = "re_plan"


class DatasetFreshnessStatus(StrEnum):
    """`DatasetFreshnessRecord.status` (data-model.md §11, FR-060)."""

    FRESH = "fresh"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


_RUN_STATUS_VALUES = tuple(s.value for s in RunStatus)
_TASK_STATUS_VALUES = tuple(s.value for s in TaskStatus)
_APPROVAL_STATUS_VALUES = tuple(s.value for s in ApprovalStatus)
_DEPENDENCY_STATE_VALUES = tuple(s.value for s in DependencyState)
_DATASET_FRESHNESS_VALUES = tuple(s.value for s in DatasetFreshnessStatus)
