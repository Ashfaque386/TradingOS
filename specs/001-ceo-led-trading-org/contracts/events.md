# Contract — Organizational Event Catalogue

**Feature**: CEO-Led AI Trading Organization | **Date**: 2026-09-10

Every event is (a) an append-only `organizational_events` row (`(run_id, sequence)` unique, gap-free per run), (b) published to Redis channel **`organization:events`** as compact JSON, and (c) for the *meaningful-action* subset, an `AuditLog` hash-chain entry (FR-140…142). Events are produced **only from real state transitions** — never fabricated, never emitted for a simulated action (FR-141, constitution VI). The console's live view and run replay both read these rows, so they cannot diverge.

## Envelope

```json
{
  "run_id": "uuid",
  "sequence": 42,
  "event_type": "task.dependency_satisfied",
  "subject_type": "task",
  "subject_id": "uuid",
  "payload": { "...": "display-ready, type-specific" },
  "occurred_at": "2026-09-10T09:11:04.512Z"
}
```

## Catalogue

| event_type | subject | Emitted when | Audited? | Key payload fields |
|---|---|---|---|---|
| `organization.run.queued` | run | objective accepted but at concurrency cap | yes | `objective`, `source`, `queue_position` |
| `organization.run.planning` | run | promoted to planning | yes | `objective` |
| `organization.plan.created` | plan | CEO plan validated | yes | `task_count`, `departments[]`, `dependency_count` |
| `organization.plan.superseded` | plan | CEO re-plans mid-run | yes | `reason`, `new_plan_id` |
| `organization.run.cannot_plan` | run | planner exhausted retries | yes | `reason` |
| `organization.run.running` | run | first task starts | no | — |
| `organization.run.waiting` | run | all runnable tasks are waiting/blocked | no | `blocking_task_ids[]` |
| `organization.run.stalled` | run | no task progress for `ORG_RUN_STALL_SECONDS` | yes | `since` |
| `organization.run.paused` / `.resumed` | run | pause/resume action | yes | `actor` |
| `organization.run.completed` / `.failed` / `.cancelled` | run | terminal | yes | `result_summary` \| `failure_reason` \| `actor` |
| `task.created` | task | plan expanded into task rows | no | `assigned_agent`, `capability`, `priority` |
| `task.ready` | task | all dependencies satisfied + agent available | no | — |
| `task.waiting_for_dependency` | task | a hard dependency is unmet | no | `waiting_for` (artefact type), `owner_task_id`, `owner_agent` |
| `task.waiting_for_agent` | task | assigned agent busy / at concurrency limit | no | `assigned_agent` |
| `task.started` | task | worker claimed it | no | `agent_run_id`, `model_used?`, `provider_used?`, `ran_concurrently` |
| `task.completed` | task | agent produced its artefact | no | `result_artefact_id`, `artefact_type`, `duration_seconds` |
| `task.blocked` | task | dependency can never be satisfied / dataset stale | yes | `blocked_reason` |
| `task.failed` | task | retry budget exhausted | yes | `failure_reason`, `retry_count` |
| `task.retrying` | task | transient failure, retrying | no | `attempt`, `error` |
| `task.escalated` | task | agent escalates to CEO | yes | `reason` |
| `task.cancelled` / `task.superseded` | task | run cancelled / re-plan replaced it | no | — |
| `dependency.satisfied` | dependency | prerequisite task completed with the needed artefact | no | `dependent_task_id`, `required_artefact_type` |
| `dependency.failed` | dependency | prerequisite ended failed/blocked, no alternative producer | yes | `dependent_task_id`, `reason` |
| `result.created` | artefact | artefact persisted | no | `artefact_type`, `task_id`, `coverage` |
| `result.consumed` | artefact | a downstream task ingested it | no | `consumed_by_task_id` |
| `agent.started` | agent | an agent begins a task | no | `agent`, `task_id` |
| `agent.completed` / `agent.failed` | agent | agent finishes a task | no (`failed`: yes) | `agent`, `task_id`, `outcome` |
| `agent.disabled` / `agent.enabled` | agent | control state changed (US9) | yes | `agent`, `actor`, `reason` |
| `agent.fallback` | agent | provider/model fell back per precedence | yes | `agent`, `from`, `to`, `reason` |
| `review.requested` | task | CEO asks for specialist peer review | no | `reviewer_agent`, `subject_task_id` |
| `review.completed` | task | reviewer returns a verdict | no | `reviewer_agent`, `verdict` |
| `ceo.decision.created` | decision | any `OrganizationalDecision` written | yes | `decision_type`, `summary`, `next_step`, `supporting_agents[]` |
| `ceo.conflict_detected` | decision | deterministic comparator finds opposing signals | yes | `conflicting_artefacts[]`, `signals` |
| `approval.requested` | approval | run produced a `DeploymentRecommendation` | yes | `approval_id`, `strategy_id` |
| `approval.approved` / `approval.rejected` | approval | SA/PM decides (clarify Q1) | yes | `decided_by`, `reason?` |
| `dataset.stale` / `dataset.refreshed` / `dataset.ingestion_failed` | — (dataset name in payload) | freshness status change (FR-062/064) | `stale`/`failed`: yes | `dataset_name`, `status`, `last_successful_update`, `checksum_ok` |

## Ordering & delivery

- `sequence` is assigned under the same transaction as the state change (gap-free). Consumers that miss messages recover via `GET /organization/runs/{id}/events?after_sequence=N`.
- Redis delivery is best-effort/at-most-once; the Postgres rows are the durable truth. The console treats the stream as a hint to refetch/patch, never as the sole source (matches the existing tick-relay philosophy).
- No event carries private model chain-of-thought (FR-023, FR-035 of the spec's CEO-activity requirement) — `ceo.decision.created` payloads are operational summaries only.
