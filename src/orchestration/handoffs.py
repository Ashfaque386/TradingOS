"""Agent-to-agent handoffs (spec 002 US3, data-model.md §1): a first-class, queryable view of
every artefact exchange between two tasks in a run.

Derived, not stored -- every field here already exists on `ResultArtefact`/`Task`
(`consumed_by_task_ids`, `received_inputs`, `required_inputs`, `assigned_agent`), populated for
real by `artefact_store.mark_consumed()` and `agent_invoker.dispatch()`. This module is a
read-only join over that existing data, per the default path documented in
`specs/002-agent-organization-hardening/data-model.md` section 1. If query-time cost ever
proves material at scale, the documented fallback is a materialised `handoffs` table written in
the same transaction as `mark_consumed()` -- not needed today (runs are ~8-20 tasks, per
plan.md's own Scale/Scope).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.orchestration import ResultArtefact, Task


def _task_lookup(session: Session, run_id: uuid.UUID) -> dict[uuid.UUID, Task]:
    tasks = session.scalars(select(Task).where(Task.run_id == run_id)).all()
    return {t.id: t for t in tasks}


def list_handoffs(session: Session, run_id: uuid.UUID) -> list[dict[str, Any]]:
    """One row per (producing task -> consuming task, artefact) triple for this run, derived
    from `ResultArtefact.consumed_by_task_ids` (who actually consumed it) and the consuming
    task's own `required_inputs`/`received_inputs` (what it expected vs. what it got)."""
    tasks_by_id = _task_lookup(session, run_id)
    artefacts = session.scalars(
        select(ResultArtefact)
        .where(ResultArtefact.run_id == run_id)
        .order_by(ResultArtefact.created_at)
    ).all()

    handoffs: list[dict[str, Any]] = []
    for artefact in artefacts:
        from_task = tasks_by_id.get(artefact.task_id)
        from_agent = from_task.assigned_agent if from_task is not None else None
        for consumer_id_str in artefact.consumed_by_task_ids:
            try:
                consumer_id = uuid.UUID(consumer_id_str)
            except ValueError:
                continue
            to_task = tasks_by_id.get(consumer_id)
            received_types = (
                {i.get("type") for i in to_task.received_inputs} if to_task is not None else set()
            )
            requested_but_missing = (
                [t for t in to_task.required_inputs if t not in received_types]
                if to_task is not None
                else []
            )
            handoffs.append(
                {
                    "run_id": str(run_id),
                    "from_task_id": str(artefact.task_id),
                    "from_agent": from_agent,
                    "to_task_id": str(consumer_id),
                    "to_agent": to_task.assigned_agent if to_task is not None else None,
                    "artefact_id": str(artefact.id),
                    "artefact_type": artefact.artefact_type,
                    "delivered_at": artefact.created_at.isoformat(),
                    "requested_but_missing": requested_but_missing,
                }
            )
    return handoffs


def list_handoffs_for_agent(
    session: Session, run_id: uuid.UUID, agent_name: str
) -> dict[str, list[dict[str, Any]]]:
    """This agent's inbound (it consumed) and outbound (it produced, someone else consumed)
    handoffs for one run -- used by the Agent Workspace (US4)."""
    all_handoffs = list_handoffs(session, run_id)
    return {
        "inbound": [h for h in all_handoffs if h["to_agent"] == agent_name],
        "outbound": [h for h in all_handoffs if h["from_agent"] == agent_name],
    }
