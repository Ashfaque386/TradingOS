# Data Model Notes: Agent Organization Hardening

This feature is deliberately data-model-light — ten of eleven user stories reuse existing tables/columns exactly as they are. This file documents the two places where a schema-adjacent decision is actually required.

## 1. Handoffs (US3) — derived, not stored (default path)

A "handoff" is fully reconstructable from existing rows:

```
Handoff = {
  run_id:            ResultArtefact.run_id
  from_task_id:      ResultArtefact.task_id
  from_agent:        Task.assigned_agent  (join on from_task_id)
  to_task_id:        <task id in ResultArtefact.consumed_by_task_ids>
  to_agent:          Task.assigned_agent  (join on to_task_id)
  artefact_id:       ResultArtefact.id
  artefact_type:     ResultArtefact.artefact_type
  delivered_at:      ResultArtefact.produced_at  (or the consuming task's dispatch time, whichever the UI needs — decide in T-phase)
  requested_but_missing: Task.required_inputs - Task.received_inputs  (for the `to_task_id` task, at its own dispatch time)
}
```

`src/orchestration/handoffs.py::list_handoffs(session, run_id)` computes this as a query-time join — no new table, no new write path, no migration. This is the default and expected implementation.

**Fallback (only if query-time cost proves material during implementation)**: a materialized `handoffs` table populated in the same transaction as `artefact_store.mark_consumed()` — same shape as above, `(run_id, from_task_id, to_task_id, artefact_id)` unique. If this fallback is taken, it needs an Alembic migration; the default path needs none. Record which path was taken in tasks.md's completion note for the relevant task, matching `001-ceo-led-trading-org`'s own practice of recording "Partial"/deferred/actual-implementation notes on tasks.

## 2. `audit_reference` write-path (US11)

The columns already exist (`OrganizationalDecision.audit_reference`, `ResultArtefact.audit_reference`, `Task.audit_reference` — `src/models/orchestration.py`). No migration is needed. What's missing is purely a write-path change:

- `events.py::emit(..., audited: bool)` currently writes an `AuditLog` row internally but returns only the `OrganizationalEvent`. Change its return type to `(OrganizationalEvent, AuditLog | None)` (or add an `audit_log_id` attribute to the returned event object) so callers can capture the id.
- `decisions.py::record_decision()`, `artefact_store.py::persist_artefact()`, and the task-transition write sites in `task_engine.py` each already call `events.emit(..., audited=True)` for the relevant transition — each needs exactly one added line: `row.audit_reference = audit_log_id` before commit.
- No new column, no new table, no new index.

## 3. `TaskStatus` enum change (US7)

Dropping `AWAITING_APPROVAL`, `WAITING_FOR_AGENT`, `SUPERSEDED` from `src/orchestration/enums.py::TaskStatus`:

- Verify whether the `tasks.status` column has a Postgres CHECK constraint enumerating these values (check the `eb7e9528f695_orchestration_core` migration). If yes, a new migration must narrow the CHECK constraint (safe — confirm zero existing rows use the three removed values first, via a pre-migration data check, since none of the code paths ever assign them per spec.md's Verification #7).
- If the column is a plain `VARCHAR` validated only at the Python/Pydantic layer (no DB CHECK), no migration is needed — only the Python enum and any `.status.in_([...])` filter expressions referencing the removed values change.
- Either way: confirm via `grep -rn "AWAITING_APPROVAL\|WAITING_FOR_AGENT\|SUPERSEDED" src/ frontend/src/` returns zero references after the change.

No other schema changes are required for this feature.
