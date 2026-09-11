"""Agent dispatch for the task engine (spec T035/T036, FR-005, FR-020).

``dispatch`` runs one task: it checks the assigned agent is available (enabled + capability
known), gathers the upstream artefacts the task depends on, invokes the capability handler, and
persists the result as a typed ``ResultArtefact`` with provenance.

T113 (closing the US4/US6 handler-binding deferral that T036/T055/T077 each chained onto the
next story without ever landing): ``market_analysis`` calls the real ``market_analyst_node``
standalone; ``news_ingestion``/``sentiment_analysis`` read the real, already-scored data the
scheduled ``run_news_sentiment_cycle`` job writes to the ``news_sentiment`` Qdrant collection
(never re-run ingestion synchronously inside a task -- that would duplicate a job that already
runs every 30 minutes and make an org task wait on network I/O it doesn't own); ``portfolio_read``
queries the real ``portfolio_positions`` table for the seeded Paper account. ``synthesize`` /
``orchestrate`` / ``context_assembly`` / ``adhoc_synthesis`` were already real (T035/T054/T146).
Still an honest placeholder: the composite ``strategy_research`` capability (running the full
``build_graph()`` sub-graph synchronously from inside a task is a materially bigger, safety-
adjacent integration -- constitution IV's safety-ordering still applies unchanged inside that
sub-graph either way, but doing it correctly needs its own reviewed task, not a drive-by addition
here) -- tracked as tasks.md T113b for a dedicated pass.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents.control import is_agent_enabled
from src.agents.llm_router import NoProviderAvailableError, complete, pop_last_call_info
from src.agents.nodes.common import extract_json
from src.models.orchestration import ResultArtefact, Task, TaskDependency
from src.orchestration import artefact_store, events, freshness
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


def _record_llm_provenance(session: Session, task: Task) -> tuple[str | None, str | None]:
    """T105 (brief §84, quickstart Scenario 10, SC-018): reads the real (provider, model,
    fell_back) `complete()` just recorded (`llm_router.pop_last_call_info`) and returns the
    *actual* provider/model used for this handler's provenance -- never the old hardcoded
    ``"orchestration-chain"``/``"research-chain"`` placeholder labels. When the chain had to fall
    back past an earlier failed provider, emits a real, audited ``agent.fallback`` event naming
    which provider(s) failed and which one actually served the call."""
    info = pop_last_call_info()
    if info is None:
        return None, None
    if info.fell_back:
        events.emit(
            session,
            run_id=task.run_id,
            event_type="agent.fallback",
            subject_type="task",
            subject_id=task.id,
            payload={
                "failed_providers": info.failed_providers,
                "provider_used": info.provider,
                "model_used": info.model,
            },
            audited=True,
        )
    return info.provider, info.model


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
        provider_used, model_used = _record_llm_provenance(session, task)
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
        provider_used, model_used = None, None
    return (
        "CeoSynthesis",
        payload,
        {"provider_used": provider_used, "model_used": model_used, "tools_used": []},
    )


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
        provider_used, model_used = _record_llm_provenance(session, task)
    except (NoProviderAvailableError, ValueError, KeyError) as exc:
        logger.warning("adhoc_synthesis_fallback", task_id=str(task.id), error=str(exc))
        answer = (
            f"Unable to complete a full analysis ({exc}); "
            f"{len(upstream)} upstream artefact(s) were collected."
        )
        supporting = [a.artefact_type for a in upstream]
        provider_used, model_used = None, None
    payload = {
        "question": task.objective,
        "answer": answer,
        "supporting_data": {
            "points": supporting,
            "upstream_types": [a.artefact_type for a in upstream],
        },
    }
    return (
        "AdHocAnalysis",
        payload,
        {"provider_used": provider_used, "model_used": model_used, "tools_used": []},
    )


def _placeholder_handler(
    session: Session, task: Task, upstream: list[ResultArtefact]
) -> HandlerResult:
    """Honestly-labelled placeholder artefact of the task's declared type -- keeps the engine
    exercisable while the real handler for this capability doesn't exist yet (currently just
    ``strategy_research``, T113 -- see its module docstring)."""
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


# --- real per-agent handlers (T113) ---------------------------------------------------------------


def _market_analysis_handler(
    session: Session, task: Task, upstream: list[ResultArtefact]
) -> HandlerResult:
    """Real Market Analyst Agent call. A minimal ``TradingOSGraphState`` is enough --
    ``market_analyst_node`` only reads ``state.research_directive``, which is ``None`` here
    exactly as it is on the graph's own first node in `trigger_research`'s entry state (not a
    synthetic input invented for this seam)."""
    from src.agents.nodes.market_analyst import market_analyst_node
    from src.agents.state import TradingOSGraphState

    try:
        result = market_analyst_node(TradingOSGraphState(thread_id=f"org-task-{task.id}"))
        payload = result["market_context"].model_dump(mode="json")
        provider_used, model_used = _record_llm_provenance(session, task)
    except Exception as exc:  # noqa: BLE001 -- an honest failed-analysis artefact beats a crash
        logger.warning("market_analysis_handler_failed", task_id=str(task.id), error=str(exc))
        payload = {
            "market_regime": "Sideways",
            "sector_rankings": [],
            "volatility_assessment": f"unavailable: {exc}",
            "macro_outlook": f"unavailable: {exc}",
            "confidence_score": 0.0,
            "insights": [],
        }
        provider_used, model_used = None, None
    return (
        "MarketContext",
        payload,
        {
            "provider_used": provider_used,
            "model_used": model_used,
            "tools_used": ["market_analyst_node"],
        },
    )


def _recent_news_sentiment_points(limit: int = 200) -> list[dict[str, Any]]:
    """Real, unfiltered scroll (no query vector -- this is "what's there", not semantic search)
    over the ``news_sentiment`` Qdrant collection, newest-first by ``published_at``. Shared by
    ``news_ingestion`` and ``sentiment_analysis`` so both see exactly the same real data the
    scheduled ``run_news_sentiment_cycle`` job wrote via ``ingest_news_sentiment``."""
    from qdrant_client import QdrantClient

    from src.core.config import get_settings

    client = QdrantClient(url=get_settings().qdrant_url)
    points, _ = client.scroll(collection_name="news_sentiment", limit=limit, with_payload=True)
    rows = [p.payload for p in points if p.payload]
    rows.sort(key=lambda r: r.get("published_at") or "", reverse=True)
    return rows


# Matches the "news" dataset's own documented freshness rule (freshness.KNOWN_DATASETS: "fresh if
# updated within the last 2 hours") with slack for the digest to still show the last real cycle's
# output rather than going empty the instant the cadence window closes; `reduced_coverage` (not
# this window) is what tells a consumer the data is stale, per FR-044.
_NEWS_RECENCY_WINDOW = timedelta(hours=6)


def _recent_within_window(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    recent = []
    for row in rows:
        published_at = row.get("published_at")
        if published_at:
            try:
                ts = datetime.fromisoformat(published_at)
            except ValueError:
                recent.append(row)
                continue
            if now - ts > _NEWS_RECENCY_WINDOW:
                continue
        recent.append(row)
    return recent


def _news_ingestion_handler(
    session: Session, task: Task, upstream: list[ResultArtefact]
) -> HandlerResult:
    """Real ``NewsDigest`` built from the ``news_sentiment`` Qdrant collection -- reads what the
    scheduled ingestion cycle already wrote rather than re-running RSS ingestion synchronously
    inside a task (FR-040)."""
    recent = _recent_within_window(_recent_news_sentiment_points())
    fresh = freshness.is_fresh(session, "news")
    headlines = [
        {"title": r.get("title", ""), "source": r.get("source", ""), "url": r.get("url", "")}
        for r in recent[:20]
    ]
    symbols = sorted({s for r in recent for s in (r.get("symbols_mentioned") or [])})
    sources = {r.get("source") for r in recent if r.get("source")}
    payload = {
        "headlines": headlines,
        "affected_symbols": symbols,
        "affected_sectors": [],
        "urgency": "Routine",
        "source_count": len(sources),
        "reduced_coverage": (not fresh) or not recent,
    }
    return "NewsDigest", payload, {"tools_used": ["news_sentiment_qdrant_scroll"]}


_SENTIMENT_SCORE = {"bullish": 1.0, "neutral": 0.0, "bearish": -1.0}


def _sentiment_analysis_handler(
    session: Session, task: Task, upstream: list[ResultArtefact]
) -> HandlerResult:
    """Real ``SentimentReport`` aggregated from the same scored ``news_sentiment`` points --
    per-symbol mean of the Sentiment Agent's own bullish/neutral/bearish score, never a fabricated
    number when no item mentions a symbol (that symbol is just absent from ``per_symbol``)."""
    recent = _recent_within_window(_recent_news_sentiment_points())
    per_symbol_scores: dict[str, list[float]] = {}
    confidences: list[float] = []
    for row in recent:
        score = _SENTIMENT_SCORE.get(str(row.get("sentiment", "")).lower())
        confidence = row.get("confidence")
        if isinstance(confidence, int | float):
            confidences.append(float(confidence))
        if score is None:
            continue
        for symbol in row.get("symbols_mentioned") or []:
            per_symbol_scores.setdefault(symbol, []).append(score)
    per_symbol = {sym: sum(vals) / len(vals) for sym, vals in per_symbol_scores.items()}
    payload = {
        "per_symbol": per_symbol,
        "per_sector": {},
        "trending_topics": [],
        "confidence": (sum(confidences) / len(confidences)) if confidences else 0.0,
        "sample_size": len(recent),
    }
    return "SentimentReport", payload, {"tools_used": ["news_sentiment_qdrant_scroll"]}


def _portfolio_read_handler(
    session: Session, task: Task, upstream: list[ResultArtefact]
) -> HandlerResult:
    """Real ``PortfolioRiskReport`` snapshot from ``portfolio_positions`` for the seeded Paper
    account -- the same table/lookup ``fetch_portfolio_status`` and the risk pipeline already use
    (FR-043); no seeded account is a real, honest empty state, not a fabricated one."""
    from src.engine.paper_trading.paper_account import get_paper_account
    from src.models.trading import PortfolioPosition

    try:
        account = get_paper_account(session)
    except RuntimeError as exc:
        return (
            "PortfolioRiskReport",
            {"exposures": {}, "highest_risk_positions": [], "notes": str(exc)},
            {"tools_used": ["portfolio_positions_query"]},
        )

    positions = list(
        session.scalars(
            select(PortfolioPosition).where(PortfolioPosition.account_id == account.id)
        ).all()
    )
    exposures = {p.symbol: float(p.net_quantity) * float(p.avg_price or 0.0) for p in positions}
    ranked = sorted(positions, key=lambda p: float(p.unrealized_pnl))[:5]
    highest_risk: list[dict[str, Any]] = [
        {
            "symbol": p.symbol,
            "net_quantity": p.net_quantity,
            "unrealized_pnl": float(p.unrealized_pnl),
        }
        for p in ranked
    ]
    payload = {
        "total_capital": None,
        "used_capital": None,
        "available_to_trade": None,
        "exposures": exposures,
        "highest_risk_positions": highest_risk,
        "notes": f"{len(positions)} open position(s)" if positions else "no open positions",
    }
    return "PortfolioRiskReport", payload, {"tools_used": ["portfolio_positions_query"]}


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
        "sector_rankings": (market.payload.get("sector_rankings", []) if market else []),
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
    "market_analysis": _market_analysis_handler,
    "news_ingestion": _news_ingestion_handler,
    "sentiment_analysis": _sentiment_analysis_handler,
    "portfolio_read": _portfolio_read_handler,
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
        model_used=prov_extra.get("model_used"),
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
