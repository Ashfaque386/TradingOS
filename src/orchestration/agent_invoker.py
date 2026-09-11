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
from src.orchestration import artefact_store, freshness
from src.orchestration.capability_registry import AGENT_META
from src.orchestration.enums import ArtefactDisposition

logger = structlog.get_logger(__name__)

HandlerResult = tuple[str, dict[str, Any], dict[str, Any]]
Handler = Callable[[Session, Task, list[ResultArtefact]], HandlerResult]


class AgentUnavailable(RuntimeError):
    """The assigned agent cannot take the task now (disabled / unknown capability). The CEO
    unavailable-capability policy (US9) handles this; the task engine surfaces it as a failure
    for the MVP."""


class DataStaleError(RuntimeError):
    """FR-062: a required dataset is not fresh. The task engine blocks this task (never retries
    it, never fabricates data) while independent tasks continue (US7)."""

    def __init__(self, dataset: str):
        self.dataset = dataset
        super().__init__(f"data stale: {dataset}")


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


def _adhoc_synthesis_handler(
    session: Session, task: Task, upstream: list[ResultArtefact]
) -> HandlerResult:
    """US8 (FR-130): a real LLM call turns the upstream artefacts (e.g. the current portfolio
    snapshot) into a direct answer to the user's ad-hoc objective -- an ``AdHocAnalysis``
    artefact with full provenance, never a free-form guess presented as organisation output."""
    context = [{"type": a.artefact_type, "payload": a.payload} for a in upstream]
    try:
        response = complete(
            "orchestration",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the CEO Agent of TradingOS, answering a user's ad-hoc analysis "
                        "request using the real department data collected below. Return ONLY "
                        'JSON: {"answer": "...", "supporting_points": ["..."]}'
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"question": task.objective, "context": context}),
                },
            ],
        )
        parsed = json.loads(extract_json(response.choices[0].message.content))
        answer = str(parsed.get("answer", "")) or "No answer produced."
        supporting = parsed.get("supporting_points", [])
        provider_used: str | None = "orchestration-chain"
    except (NoProviderAvailableError, ValueError, KeyError) as exc:
        logger.warning("adhoc_synthesis_fallback", task_id=str(task.id), error=str(exc))
        answer = (
            f"Unable to complete a full analysis ({exc}); "
            f"{len(upstream)} upstream artefact(s) were collected."
        )
        supporting = [a.artefact_type for a in upstream]
        provider_used = None
    payload = {
        "question": task.objective,
        "answer": answer,
        "supporting_data": {
            "points": supporting,
            "upstream_types": [a.artefact_type for a in upstream],
        },
    }
    return "AdHocAnalysis", payload, {"provider_used": provider_used, "tools_used": []}


# Minimal schema-valid payloads per context capability, so the placeholder path still produces
# *correctly typed* NewsDigest / SentimentReport / PortfolioRiskReport artefacts (their real
# per-agent handlers are wired in a later phase -- US6). Provenance still links every source.
_CONTEXT_PLACEHOLDERS: dict[str, tuple[str, dict[str, Any]]] = {
    "news_ingestion": (
        "NewsDigest",
        {"headlines": [], "source_count": 1, "reduced_coverage": False},
    ),
    "sentiment_analysis": ("SentimentReport", {"per_symbol": {}, "per_sector": {}}),
    "portfolio_read": ("PortfolioRiskReport", {"exposures": {}, "notes": "placeholder snapshot"}),
    "market_analysis": (
        "MarketContext",
        {
            "market_regime": "Sideways",
            "sector_rankings": [],
            "volatility_assessment": "unknown (placeholder)",
            "macro_outlook": "unknown (placeholder)",
            "confidence_score": 0.0,
            "insights": [],
        },
    ),
}


def _placeholder_handler(
    session: Session, task: Task, upstream: list[ResultArtefact]
) -> HandlerResult:
    """Honestly-labelled placeholder artefact of the task's declared type -- keeps the engine
    exercisable while the real handler for this capability is a later phase."""
    from src.core.config import get_settings

    delay = get_settings().org_placeholder_task_delay_seconds
    if delay > 0:
        time.sleep(delay)

    typed = _CONTEXT_PLACEHOLDERS.get(task.capability)
    if typed is not None:
        artefact_type, typed_payload = typed
        return artefact_type, dict(typed_payload), {"tools_used": []}

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


# --- context assembly (T054, FR-042/044) ---------------------------------------------------------

_CONTEXT_SOURCES = ("NewsDigest", "SentimentReport", "PortfolioRiskReport", "MarketContext")


def _context_assembly_handler(
    session: Session, task: Task, upstream: list[ResultArtefact]
) -> HandlerResult:
    """Assemble a ``ResearchContext`` from this run's news / sentiment / portfolio / market /
    freshness artefacts. A source that is legitimately absent (a ``soft`` dependency that never
    produced) is recorded in ``missing_inputs`` and drops ``coverage`` to ``reduced`` (FR-044) --
    the context is never presented as complete when it is not."""
    by_type: dict[str, ResultArtefact] = {}
    for a in upstream:
        by_type.setdefault(a.artefact_type, a)

    news = by_type.get("NewsDigest")
    sentiment = by_type.get("SentimentReport")
    portfolio = by_type.get("PortfolioRiskReport")
    market = by_type.get("MarketContext")

    missing = [s for s in _CONTEXT_SOURCES if s not in by_type]
    reduced_news = bool(news and news.payload.get("reduced_coverage"))
    coverage = "reduced" if (missing or reduced_news) else "full"

    sentiment_map: dict[str, float] = {}
    if sentiment is not None:
        sentiment_map = {
            **(sentiment.payload.get("per_symbol") or {}),
            **{f"sector:{k}": v for k, v in (sentiment.payload.get("per_sector") or {}).items()},
        }

    payload: dict[str, Any] = {
        "market_regime": (market.payload.get("market_regime") if market is not None else None),
        "sector_strengths": (market.payload.get("sector_strengths", {}) if market else {}),
        "news_summary": (
            f"{len(news.payload.get('headlines', []))} headline(s)"
            if news is not None
            else "no news feed available"
        ),
        "sentiment": sentiment_map,
        "portfolio_exposure": (portfolio.payload.get("exposures", {}) if portfolio else {}),
        "risk_posture": None,
        "coverage": coverage,
        "missing_inputs": missing,
    }
    return "ResearchContext", payload, {"tools_used": ["context_assembly"]}


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
    "context_assembly": _context_assembly_handler,
    "adhoc_synthesis": _adhoc_synthesis_handler,
}


def dispatch(session: Session, task: Task) -> ResultArtefact:
    """Run one task; persist and return its result artefact. Raises ``AgentUnavailable`` if the
    assigned agent is disabled or its capability is unknown (FR-005)."""
    if task.assigned_agent not in AGENT_META:
        raise AgentUnavailable(f"unknown agent '{task.assigned_agent}'")
    if not is_agent_enabled(session, task.assigned_agent):
        raise AgentUnavailable(f"agent '{task.assigned_agent}' is administratively disabled")

    for dataset in task.required_datasets or []:
        if not freshness.is_fresh(session, dataset):
            raise DataStaleError(dataset)

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
