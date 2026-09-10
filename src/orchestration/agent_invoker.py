"""Agent dispatch for the task engine (spec T035/T036, FR-005, FR-020).

``dispatch`` runs one task: it checks the assigned agent is available (enabled + capability
known), gathers the upstream artefacts the task depends on, invokes the capability handler, and
persists the result as a typed ``ResultArtefact`` with provenance.

MVP scope: the ``synthesize`` capability makes a real ``complete()`` call; every other
capability currently produces an honestly-labelled placeholder artefact so the *engine*
(parallelism, dependency-aware waiting, lifecycle, events) is fully exercisable end to end. The
real per-agent handlers (market/news/sentiment via the existing node functions, the composite
``strategy_research`` sub-graph via ``build_graph()``) are wired by the US4/US6 phases -- the
handler table below is the single seam for that.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents.control import is_agent_enabled
from src.agents.llm_router import NoProviderAvailableError, complete
from src.agents.nodes.common import extract_json
from src.models.orchestration import ResultArtefact, Task, TaskDependency
from src.orchestration import artefact_store
from src.orchestration.capability_registry import AGENT_META
from src.orchestration.enums import ArtefactDisposition

logger = structlog.get_logger(__name__)

HandlerResult = tuple[str, dict[str, Any], dict[str, Any]]
Handler = Callable[[Session, Task, list[ResultArtefact]], HandlerResult]


class AgentUnavailable(RuntimeError):
    """The assigned agent cannot take the task now (disabled / unknown capability). The CEO
    unavailable-capability policy (US9) handles this; the task engine surfaces it as a failure
    for the MVP."""


def _upstream_artefacts(session: Session, task: Task) -> list[ResultArtefact]:
    dep_task_ids = list(
        session.scalars(
            select(TaskDependency.prerequisite_task_id).where(
                TaskDependency.dependent_task_id == task.id
            )
        ).all()
    )
    if not dep_task_ids:
        return []
    return list(
        session.scalars(
            select(ResultArtefact).where(ResultArtefact.task_id.in_(dep_task_ids))
        ).all()
    )


def _synthesize_handler(
    session: Session, task: Task, upstream: list[ResultArtefact]
) -> HandlerResult:
    """Real LLM call: the CEO turns the upstream artefacts into a plain-language synthesis
    (FR-023 -- operational summary, no private reasoning)."""
    context = [{"type": a.artefact_type, "payload": a.payload} for a in upstream]
    try:
        response = complete(
            "orchestration",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the CEO Agent of TradingOS. Summarise the department outputs "
                        "below into a concise operational synthesis. Return ONLY JSON: "
                        '{"summary": "...", "recommendation": "...", "key_findings": ["..."], '
                        '"next_step": "..."}'
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"objective": task.objective, "context": context}),
                },
            ],
        )
        payload = json.loads(extract_json(response.choices[0].message.content))
        payload.setdefault("summary", task.objective)
        provider_used = "orchestration-chain"
    except (NoProviderAvailableError, ValueError, KeyError) as exc:
        logger.warning("synthesize_fallback", task_id=str(task.id), error=str(exc))
        payload = {
            "summary": (
                f"Synthesis unavailable ({exc}); "
                f"{len(upstream)} upstream artefact(s) collected."
            ),
            "recommendation": "",
            "key_findings": [a.artefact_type for a in upstream],
            "next_step": None,
        }
        provider_used = None
    return "CeoSynthesis", payload, {"provider_used": provider_used, "tools_used": []}


def _placeholder_handler(
    session: Session, task: Task, upstream: list[ResultArtefact]
) -> HandlerResult:
    """Honestly-labelled placeholder artefact of the task's declared type -- keeps the engine
    exercisable while the real handler for this capability is a later phase."""
    from src.core.config import get_settings

    delay = get_settings().org_placeholder_task_delay_seconds
    if delay > 0:
        time.sleep(delay)
    schema_type = task.expected_output or "AdHocAnalysis"
    payload: dict[str, Any] = {
        "question": task.objective,
        "answer": (
            f"[placeholder] '{task.capability}' handler not yet wired; "
            f"{len(upstream)} upstream artefact(s) available."
        ),
        "supporting_data": {"upstream_types": [a.artefact_type for a in upstream]},
    }
    # Fall back to the AdHocAnalysis shape if the declared type has a stricter schema.
    return _coerce_or_adhoc(schema_type, payload), payload, {"tools_used": []}


def _coerce_or_adhoc(schema_type: str, payload: dict[str, Any]) -> str:
    from src.orchestration.artefact_schemas import ARTEFACT_SCHEMA_REGISTRY

    model = ARTEFACT_SCHEMA_REGISTRY.get(schema_type)
    if model is None:
        return "AdHocAnalysis"
    try:
        model.model_validate(payload)
        return schema_type
    except Exception:  # noqa: BLE001 -- placeholder can't satisfy every strict schema; that's fine
        return "AdHocAnalysis"


CAPABILITY_HANDLERS: dict[str, Handler] = {
    "synthesize": _synthesize_handler,
    "orchestrate": _synthesize_handler,
}


def dispatch(session: Session, task: Task) -> ResultArtefact:
    """Run one task; persist and return its result artefact. Raises ``AgentUnavailable`` if the
    assigned agent is disabled or its capability is unknown (FR-005)."""
    if task.assigned_agent not in AGENT_META:
        raise AgentUnavailable(f"unknown agent '{task.assigned_agent}'")
    if not is_agent_enabled(session, task.assigned_agent):
        raise AgentUnavailable(f"agent '{task.assigned_agent}' is administratively disabled")

    upstream = _upstream_artefacts(session, task)
    for a in upstream:
        artefact_store.mark_consumed(session, artefact_id=a.id, by_task_id=task.id)
    task.received_inputs = [{"artefact_id": str(a.id), "type": a.artefact_type} for a in upstream]

    handler = CAPABILITY_HANDLERS.get(task.capability, _placeholder_handler)
    artefact_type, payload, prov_extra = handler(session, task, upstream)

    provenance = artefact_store.build_provenance(
        agent=task.assigned_agent,
        task_id=task.id,
        run_id=task.run_id,
        provider_used=prov_extra.get("provider_used"),
        tools_used=prov_extra.get("tools_used", []),
        inputs=[str(a.id) for a in upstream],
    )
    artefact = artefact_store.persist_artefact(
        session,
        run_id=task.run_id,
        task_id=task.id,
        artefact_type=artefact_type,
        payload=payload,
        provenance=provenance,
        disposition=ArtefactDisposition.INFORMATIONAL,
    )
    task.result_artefact_id = artefact.id
    session.flush()
    return artefact
