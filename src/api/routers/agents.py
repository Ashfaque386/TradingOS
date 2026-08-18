"""Agent Console endpoints (Phase 4 Epic E4.3), backing Phase_7_Frontend_Architecture.md §2.1:

  - GET  /agents/graph                     -- static LangGraph topology (nodes/edges), real,
    introspected from the actual compiled graph (`build_graph().get_graph()`), not hand-copied.
  - POST /agents/research/trigger          -- starts a real graph run (real LLM calls through
    every node) in the background; returns immediately with a run id.
  - GET  /agents/runs                      -- recent graph-run history (DB-012 AgentRun).
  - GET  /agents/runs/{run_id}             -- one run's per-node child runs + their logs.
  - GET  /agents/prompts                   -- the prompt registry manifest (src/agents/
    prompt_registry.py), which agent maps to which prompt_id/active version.
  - GET  /agents/prompts/{slug}/versions/{version} -- a specific prompt version's content.
  - PUT  /agents/prompts/{slug}/active-version      -- hot-swap which version is active.

Before this router existed, nothing in the codebase ever invoked `build_graph()` outside tests,
and nothing ever called `publish_agent_log()` outside a test fixture -- the graph was real but
never run, and the `/stream/agents/logs` WS relay had no producer. `_execute_graph_run` below is
that producer: it streams the graph's real per-node execution (LangGraph's `stream_mode="updates"`
gives one real output dict per node as it actually completes -- no fabricated data), persists an
AgentRun/AgentLog row per node (DB-012/DB-013, previously defined but never written to), and
publishes each step to Redis so the Thought Stream panel has real content to show.

Auth/RBAC gap matches every other Phase 4 router: no JWT/auth module exists yet.
"""

import asyncio
import json
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents import prompt_registry
from src.agents.analytics import bucket_by_day, group_by_agent, summarize_runs
from src.agents.checkpointer import runtime_checkpoint_dsn
from src.agents.control import (
    KNOWN_AGENTS,
    AgentHaltedError,
    UnknownAgentError,
    set_agent_enabled,
)
from src.agents.graph import build_graph, build_suggestion_regeneration_graph
from src.agents.llm_router import fetch_langsmith_trace_url, pop_last_langsmith_run_id
from src.agents.nodes.backtesting import DEFAULT_BACKTEST_LOOKBACK_DAYS, DEFAULT_INITIAL_CAPITAL
from src.agents.nodes.suggestion_reviewer import review_suggestion
from src.agents.prompt_registry import PromptNotFoundError
from src.agents.state import (
    EquityCurvePoint,
    EvaluationVerdict,
    MarketContext,
    PythonCode,
    ResearchDirective,
    StrategyOptionLeg,
    TradingOSGraphState,
)
from src.api.deps import require_role
from src.brokers.factory import NoBrokerConfigured, build_broker
from src.core.audit import write_audit_entry
from src.core.config import get_settings
from src.core.db import get_session
from src.core.security import ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER, ROLE_SYSTEM_ADMINISTRATOR
from src.data.datalake.query import DataLake
from src.engine.paper_trading.account_equity import compute_account_equity
from src.engine.paper_trading.paper_account import get_paper_account
from src.engine.sandbox.strategy_factory import run_strategy_factory_pipeline
from src.memory.redis_client import get_redis_client, publish_agent_log
from src.models.account import Account, AccountEquitySnapshot
from src.models.agent import AgentControlState, AgentLog, AgentRun
from src.models.skill import AgentSkillMap, Skill
from src.models.strategy import BacktestResult, Strategy, StrategySuggestion, StrategyVersion
from src.models.user import User
from src.observability.metrics import AGENT_RUN_DURATION_SECONDS

logger = structlog.get_logger(__name__)

# No Risk Manager Agent exists yet to set a real per-strategy drawdown limit (Phase 4 scope,
# per Phase_14_Master_Development_Roadmap.md) -- mirrors kill_switch.py's
# DEFAULT_KILL_SWITCH_THRESHOLD (15%) rather than inventing an unrelated number.
_DEFAULT_MAX_DRAWDOWN_LIMIT = Decimal("15.00")

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])

GRAPH_ROOT_AGENT_NAME = "TradingOSGraph"

# REL-010 E10.8d: Orchestrator HITL (retry/approve/reject) -- the same role set src/api/routers/
# portfolio.py's E10.5 allocation-recommendation accept/reject already gates on, plus RiskManager
# since a rejected deployment recommendation is exactly the kind of decision that role exists for.
_can_manage_hitl = require_role(
    ROLE_SYSTEM_ADMINISTRATOR, ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER, audit_denials=True
)


# --- Topology -----------------------------------------------------------------------------


class GraphNode(BaseModel):
    id: str


class GraphEdge(BaseModel):
    source: str
    target: str
    conditional: bool


class GraphTopologyResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


@router.get("/graph", response_model=GraphTopologyResponse)
def get_graph_topology() -> GraphTopologyResponse:
    representation = build_graph().get_graph()
    return GraphTopologyResponse(
        nodes=[GraphNode(id=node_id) for node_id in representation.nodes],
        edges=[
            GraphEdge(source=e.source, target=e.target, conditional=e.conditional)
            for e in representation.edges
        ],
    )


# --- Per-agent control (REL-019 E19.2, ADR 11) -----------------------------------------------


class AgentControlEntry(BaseModel):
    agent_name: str
    agent_id: str
    display_name: str
    kind: str
    enforced: bool
    enabled: bool
    reason: str | None
    updated_by: str | None
    updated_at: datetime | None


class SetAgentEnabledRequest(BaseModel):
    enabled: bool
    reason: str | None = None


@router.get("/control", response_model=list[AgentControlEntry])
def list_agent_control_state() -> list[AgentControlEntry]:
    """The full real-agent registry (src/agents/control.py::KNOWN_AGENTS) joined against the
    real `agent_control_state` table -- an agent with no row is genuinely enabled (fail-open
    default), not a placeholder; `enforced` tells the console honestly whether a call site
    actually checks this agent's state yet (see control.py's module docstring)."""
    with get_session() as session:
        rows = {row.agent_name: row for row in session.scalars(select(AgentControlState))}
        entries = []
        for agent in KNOWN_AGENTS:
            row = rows.get(agent.name)
            updated_by_email = None
            if row is not None and row.updated_by_user_id is not None:
                user = session.get(User, row.updated_by_user_id)
                updated_by_email = user.email if user is not None else None
            entries.append(
                AgentControlEntry(
                    agent_name=agent.name,
                    agent_id=agent.agent_id,
                    display_name=agent.display_name,
                    kind=agent.kind,
                    enforced=agent.enforced,
                    enabled=row is None or row.enabled,
                    reason=row.reason if row is not None else None,
                    updated_by=updated_by_email,
                    updated_at=row.updated_at if row is not None else None,
                )
            )
        return entries


@router.put("/control/{agent_name}", response_model=AgentControlEntry)
def set_agent_control_state(
    agent_name: str,
    body: SetAgentEnabledRequest,
    user: User = Depends(_can_manage_hitl),
) -> AgentControlEntry:
    """Toggles one agent's real, durable enabled/disabled state. Refuses to disable the Audit
    Agent (Business Rule 5) -- see control.py::set_agent_enabled. Audited the same way every
    other admin-consequential mutation in this router is (write_audit_entry)."""
    agent = next((a for a in KNOWN_AGENTS if a.name == agent_name), None)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Unknown agent '{agent_name}'")
    with get_session() as session:
        try:
            row = set_agent_enabled(
                session,
                agent_name=agent_name,
                enabled=body.enabled,
                reason=body.reason,
                updated_by_user_id=user.id,
            )
        except UnknownAgentError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=str(user.id),
            action="AGENT_CONTROL_STATE_CHANGED",
            entity_type="AgentControlState",
            entity_id=row.id,
            after_state={"agent_name": agent_name, "enabled": body.enabled, "reason": body.reason},
            prompt_snapshot=f"{'Disabled' if not body.enabled else 'Enabled'} {agent_name}"
            + (f": {body.reason}" if body.reason else ""),
        )
        session.commit()
        return AgentControlEntry(
            agent_name=agent.name,
            agent_id=agent.agent_id,
            display_name=agent.display_name,
            kind=agent.kind,
            enforced=agent.enforced,
            enabled=row.enabled,
            reason=row.reason,
            updated_by=user.email,
            updated_at=row.updated_at,
        )


# --- Trigger a real run ---------------------------------------------------------------------


class TriggerResponse(BaseModel):
    run_id: uuid.UUID
    thread_id: str
    status: str


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _summarize_node_output(node_name: str, output: dict[str, Any] | None) -> str:
    """A short, honest summary of what a node actually returned -- built from the real
    Pydantic fields in `output`, never a canned string.

    BUG-011 (see `_persist_strategy_progress`'s own `options_strategy_agent` branch for the full
    explanation): LangGraph's `updates` stream mode represents a node's empty-dict return (the
    real, intentional no-op `options_strategy_node` returns for an Equity strategy) as `output =
    None`, not `{}`. This is called before `_persist_strategy_progress`/`_persist_suggestion_
    regeneration` even run, so it was the actual FIRST crash point for every real Equity
    strategy's graph run, not the persistence layer -- `output.get(...)` on `None` raised
    `AttributeError` here before this guard existed."""
    if not output:
        return f"{node_name} completed with no new state fields"
    directive = output.get("research_directive")
    if directive is not None:
        return (
            f"Issued research directive: {directive.market_regime} regime, "
            f"sectors={directive.priority_sectors or 'none'}"
        )
    context = output.get("market_context")
    if context is not None:
        return f"Market context: confidence={context.confidence_score:.2f}, {context.macro_outlook}"
    strategy = output.get("strategy_logic")
    if strategy is not None:
        return (
            f"Proposed strategy: {strategy.hypothesis} "
            f"(confidence={strategy.confidence_score:.2f})"
        )
    code = output.get("python_code")
    if code is not None:
        return f"Generated strategy code v{code.version_no} ({len(code.code)} chars)"
    validation = output.get("validation_result")
    if validation is not None:
        if validation.status == "Pass":
            return "Validation passed"
        return f"Validation failed ({validation.severity}): {validation.feedback}"
    metrics = output.get("backtest_metrics")
    if metrics is not None:
        return (
            f"Real backtest complete: Sharpe {metrics.sharpe_ratio:.2f}, "
            f"MaxDD {metrics.max_drawdown:.2f}"
        )
    verdict = output.get("evaluation_verdict")
    if verdict is not None:
        if verdict.verdict == "PASS":
            return "Evaluation PASSED -- advancing to Optimization"
        return f"Evaluation FAILED: {'; '.join(verdict.failure_reasons)}"
    optimization = output.get("optimization_result")
    if optimization is not None:
        robust = "robust" if optimization.passed else "not robust"
        return f"Optimization {robust}: {optimization.notes}"
    risk = output.get("risk_assessment")
    if risk is not None:
        return f"Risk decision: {risk.decision}"
    deployment = output.get("deployment_recommendation")
    if deployment is not None:
        return (
            f"Deployment recommendation: {deployment.recommended_status} -- "
            f"{deployment.rationale}"
        )
    return f"{node_name} completed with no new state fields"


@dataclass
class _StrategyTracking:
    """Local-to-one-run state threaded through `_execute_graph_run`'s node loop -- not global,
    since each concurrent run builds its own Strategy/StrategyVersion lineage."""

    strategy_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    account_lookup_done: bool = False
    # REL-005: the one BacktestResult row (DB-007) this thread's current strategy attempt is
    # accumulating pipeline outcomes onto (evaluation/optimization/risk/deployment columns).
    # Reassigned every time "backtesting" fires again -- each rejected-and-regenerated strategy
    # in the Backtest_Loop gets its own real BacktestResult row, a real audit trail rather than
    # overwriting history.
    backtest_result_id: uuid.UUID | None = None
    # REL-035: the Options Strategy Agent's real, chain-grounded legs/expiry -- staged here
    # between the `options_strategy_agent` node firing and `python_code_generator` firing next
    # (the two are adjacent in the graph, see options_strategy_agent.py's own module docstring),
    # since StrategyVersion doesn't exist as a row until the latter creates it.
    pending_option_legs: list[StrategyOptionLeg] | None = None
    pending_option_expiry: date | None = None
    # REL-044: the CEO Agent's ResearchDirective and Market Analyst's MarketContext -- staged the
    # same way as the option fields above, since both nodes fire before `strategy_generator`
    # creates the Strategy row they ultimately get copied onto.
    pending_research_context: dict[str, Any] | None = None
    pending_market_context: dict[str, Any] | None = None
    # REL-044: the Options Strategy Agent's real rationale for its declared legs -- staged
    # between the `options_strategy_agent` node firing and `python_code_generator` creating the
    # StrategyVersion row it gets copied onto, mirroring pending_option_legs/expiry above.
    pending_option_rationale: str | None = None


def _persist_strategy_progress(
    session: Session,
    *,
    node_name: str,
    output: dict[str, Any],
    tracking: _StrategyTracking,
    agent_run_id: uuid.UUID,
) -> None:
    """Real persistence for DB-005/DB-006 (Strategy/StrategyVersion, src/models/strategy.py):
    before this, nothing in the codebase ever wrote a row to either table (confirmed by
    exhaustive grep before building this) -- the Strategy Deployment Kanban
    (Phase_7_Frontend_Architecture.md §2.3) had nothing to show. Mirrors the AgentRun/AgentLog
    persistence just above: hook real DB writes onto the graph's real per-node output, no
    fabricated intermediate state."""
    # REL-044: ceo_agent/market_analyst both fire before strategy_generator creates the Strategy
    # row their output ultimately gets copied onto, so these two branches must sit ahead of the
    # `tracking.strategy_id is None` gate below (which would otherwise always be true here) --
    # same staging pattern as pending_option_legs/expiry, just one node earlier in the graph.
    if node_name == "ceo_agent" and "research_directive" in output:
        tracking.pending_research_context = _jsonable(output["research_directive"])
        return

    if node_name == "market_analyst" and "market_context" in output:
        tracking.pending_market_context = _jsonable(output["market_context"])
        return

    if node_name == "strategy_generator" and "strategy_logic" in output:
        if not tracking.account_lookup_done:
            try:
                tracking.account_id = get_paper_account(session).id
            except RuntimeError:
                tracking.account_id = None
            tracking.account_lookup_done = True
        if tracking.account_id is None:
            return  # no Paper Account seeded yet -- can't satisfy Strategy.account_id's NOT NULL FK

        logic = output["strategy_logic"]
        # REL-064: the resolved Paper account already carries a real tenant_id (every existing
        # row was backfilled onto the one seeded "Primary Tenant" at migration time) -- one extra
        # lookup at this already-established write site, not a new query pattern. account_id was
        # already validated to resolve to a real row above (get_paper_account), so this is never
        # None in practice.
        account = session.get(Account, tracking.account_id)
        assert account is not None
        account_tenant_id = account.tenant_id
        strategy = Strategy(
            account_id=tracking.account_id,
            tenant_id=account_tenant_id,
            name=logic.hypothesis[:150],
            hypothesis=logic.hypothesis,
            asset_class=logic.asset_class,
            style=logic.style,
            status="Ideation",
            max_drawdown_limit=_DEFAULT_MAX_DRAWDOWN_LIMIT,
            universe=logic.universe or None,
            # REL-044: the rest of StrategyLogic -- previously computed by the LLM on every run
            # and then discarded, since Strategy had no columns for them until this release.
            entry_conditions=logic.entry_conditions,
            exit_conditions=logic.exit_conditions,
            stop_loss=logic.stop_loss,
            take_profit=logic.take_profit,
            position_sizing=logic.position_sizing,
            confidence_score=logic.confidence_score,
            research_context=tracking.pending_research_context,
            market_context=tracking.pending_market_context,
        )
        session.add(strategy)
        session.flush()
        tracking.strategy_id = strategy.id
        return

    if tracking.strategy_id is None:
        return  # strategy_generator hasn't run yet this thread (or its account lookup failed)

    # BUG-011: `options_strategy_node` returns `{}` for an Equity strategy_logic (nothing for it
    # to ground) -- src/agents/nodes/options_strategy_agent.py's own module docstring confirms
    # this is intentional, "a no-op passthrough for 'Equity' strategies." LangGraph's `updates`
    # stream mode represents that empty-dict return as `output = None` for this node's step, not
    # `{}` -- confirmed empirically (a real graph.stream() debug trace), not assumed. Without the
    # `output` truthiness guard below, `"strategy_logic" in output` raised `TypeError: argument of
    # type 'NoneType' is not iterable` for every real Equity strategy's graph run, crashing the
    # whole run right after strategy_generator and leaving it silently stuck at status="Coding"
    # forever -- every strategy that has ever reached a real BacktestResult in this codebase's
    # history was F&O, not by chance. Found while live-testing REL-048's suggestion-regeneration
    # pipeline against a real strategy the LLM happened to regenerate as Equity.
    if node_name == "options_strategy_agent" and output and "strategy_logic" in output:
        tracking.pending_option_legs = output["strategy_logic"].option_legs
        tracking.pending_option_expiry = output.get("option_expiry")
        tracking.pending_option_rationale = output.get("option_rationale")
        return

    if node_name == "python_code_generator" and "python_code" in output:
        code = output["python_code"]
        version = StrategyVersion(
            strategy_id=tracking.strategy_id,
            version_no=code.version_no,
            python_code=code.code,
            validation_status="Pending",
            option_legs=(
                [leg.model_dump() for leg in tracking.pending_option_legs]
                if tracking.pending_option_legs
                else None
            ),
            option_expiry=tracking.pending_option_expiry,
            option_rationale=tracking.pending_option_rationale,
        )
        session.add(version)
        session.flush()
        strategy_row = session.get(Strategy, tracking.strategy_id)
        if strategy_row is not None:
            strategy_row.current_version_id = version.id
            strategy_row.status = "Coding"
        return

    if node_name == "python_validator" and "validation_result" in output:
        strategy_row = session.get(Strategy, tracking.strategy_id)
        if strategy_row is None or strategy_row.current_version_id is None:
            return
        if output["validation_result"].status != "Pass":
            # a retry produces a new StrategyVersion via the branch above; nothing to do here
            return
        version_row = session.get(StrategyVersion, strategy_row.current_version_id)
        if version_row is None:
            return
        # Real sandbox re-validation + .py persistence via the tested Phase 3 pipeline (writes
        # {data_lake_root.parent}/strategies/{version_id}.py and updates
        # StrategyVersion.validation_status itself) -- reused rather than re-implemented here.
        run_strategy_factory_pipeline(
            version_row.python_code, strategy_version_id=str(version_row.id)
        )
        strategy_row.status = "Backtesting"
        return

    if node_name == "backtesting" and "backtest_metrics" in output:
        strategy_row = session.get(Strategy, tracking.strategy_id)
        if (
            strategy_row is None
            or strategy_row.current_version_id is None
            or not strategy_row.universe
        ):
            return
        lake = DataLake(get_settings().data_lake_root / "ohlcv_daily")
        date_to = lake.latest_date(strategy_row.universe[0])
        if date_to is None:
            return
        metrics = output["backtest_metrics"]
        result = BacktestResult(
            strategy_version_id=strategy_row.current_version_id,
            agent_run_id=agent_run_id,
            date_from=date_to - timedelta(days=DEFAULT_BACKTEST_LOOKBACK_DAYS),
            date_to=date_to,
            initial_capital=DEFAULT_INITIAL_CAPITAL,
            symbol=strategy_row.universe[0],
            sharpe_ratio=metrics.sharpe_ratio,
            sortino_ratio=metrics.sortino_ratio,
            calmar_ratio=metrics.calmar_ratio,
            max_drawdown=metrics.max_drawdown,
            cagr=metrics.cagr,
            win_rate=metrics.win_rate,
            profit_factor=metrics.profit_factor,
            expectancy=metrics.expectancy,
            total_trades=metrics.total_trades,
            data_adjusted=metrics.data_adjusted,
            provider_used=metrics.provider_used,
            data_retrieved_at=metrics.data_retrieved_at,
        )
        session.add(result)
        session.flush()
        tracking.backtest_result_id = result.id
        return

    if tracking.backtest_result_id is None:
        return  # backtesting hasn't produced a row this cycle (or its lookups failed)

    if node_name == "evaluator" and "evaluation_verdict" in output:
        result_row = session.get(BacktestResult, tracking.backtest_result_id)
        verdict = output["evaluation_verdict"]
        if result_row is not None:
            result_row.evaluation_verdict = verdict.verdict
            result_row.evaluation_failure_reasons = verdict.failure_reasons or None
        if verdict.verdict == "PASS":
            strategy_row = session.get(Strategy, tracking.strategy_id)
            if strategy_row is not None:
                strategy_row.status = "Optimizing"
        # FAIL: no status change -- the strategy stays "Backtesting" while the loop regenerates.
        return

    if node_name == "optimization" and "optimization_result" in output:
        result_row = session.get(BacktestResult, tracking.backtest_result_id)
        opt = output["optimization_result"]
        if result_row is not None:
            result_row.optimization_best_params = opt.best_params or None
            result_row.optimization_robustness_score = opt.robustness_score
            # REL-024: real Walk-Forward window summaries, when optimization_node had enough
            # real entries_exits/close_curve data to run them -- None (not []), matching every
            # other honestly-nothing-here JSONB column on this row, when it didn't.
            result_row.walk_forward_results = opt.walk_forward_results or None
        strategy_row = session.get(Strategy, tracking.strategy_id)
        if strategy_row is not None:
            strategy_row.status = "RiskReview"
        return

    if node_name == "risk_manager" and "risk_assessment" in output:
        result_row = session.get(BacktestResult, tracking.backtest_result_id)
        risk = output["risk_assessment"]
        if result_row is not None:
            result_row.risk_assessment_passed = risk.decision != "Reject"
            result_row.risk_assessment_notes = risk.narrative
        return

    if node_name == "deployment" and "deployment_recommendation" in output:
        result_row = session.get(BacktestResult, tracking.backtest_result_id)
        rec = output["deployment_recommendation"]
        if result_row is not None:
            result_row.deployment_recommendation = rec.recommended_status
            result_row.deployment_rationale = rec.rationale
        strategy_row = session.get(Strategy, tracking.strategy_id)
        if strategy_row is not None:
            # "Live" is never written here or anywhere in this pipeline -- that transition is
            # permanently reserved for the RBAC-gated /strategies/{id}/promote endpoint
            # (Business Rule 3, human-in-the-loop).
            strategy_row.status = (
                "PaperTrading" if rec.recommended_status == "PaperTrading" else "Deprecated"
            )
        return


def _fetch_account_capital() -> float | None:
    """REL-034: the seeded Paper Trading Account's real live equity, for `risk_manager_node`'s
    real `compute_position_sizes()` call -- `None` (not fabricated) whenever no broker is
    configured or no Paper account has been seeded yet (`scripts/seed_paper_account.py`), both
    honest, real "not available" states this codebase already has an established convention for
    (see risk_manager.py's own NOT_COMPUTED_NOTE)."""
    try:
        broker = build_broker()
    except NoBrokerConfigured:
        return None
    try:
        with get_session() as session:
            account = get_paper_account(session)
            return asyncio.run(compute_account_equity(str(account.id), session, broker))
    except RuntimeError:
        return None


def _fetch_existing_portfolio_equity_curve() -> list[EquityCurvePoint]:
    """The seeded Paper Trading Account's real daily equity history (AccountEquitySnapshot /
    account_equity_snapshots, DB-035, REL-034), for `risk_manager_node`'s correlation blend --
    empty (not fabricated) whenever no Paper account has been seeded yet or it has no snapshot
    rows. A pure DB read, unlike `_fetch_account_capital()` above -- no broker call needed."""
    try:
        with get_session() as session:
            account = get_paper_account(session)
            rows = (
                session.execute(
                    select(AccountEquitySnapshot)
                    .where(AccountEquitySnapshot.account_id == account.id)
                    .order_by(AccountEquitySnapshot.snapshot_date)
                )
                .scalars()
                .all()
            )
            return [
                EquityCurvePoint(date=row.snapshot_date.isoformat(), equity=float(row.equity))
                for row in rows
            ]
    except RuntimeError:
        return []


def _tracking_to_snapshot(tracking: _StrategyTracking) -> dict[str, Any]:
    """REL-060: `_StrategyTracking` lives outside `TradingOSGraphState` (LangGraph's own
    checkpointer only persists that), so it would otherwise be lost when `_execute_graph_run`'s
    background thread returns on a pause -- snapshotted onto the root `AgentRun` row instead."""
    return {
        "strategy_id": str(tracking.strategy_id) if tracking.strategy_id else None,
        "account_id": str(tracking.account_id) if tracking.account_id else None,
        "account_lookup_done": tracking.account_lookup_done,
        "backtest_result_id": (
            str(tracking.backtest_result_id) if tracking.backtest_result_id else None
        ),
        "pending_option_legs": (
            [leg.model_dump(mode="json") for leg in tracking.pending_option_legs]
            if tracking.pending_option_legs
            else None
        ),
        "pending_option_expiry": (
            tracking.pending_option_expiry.isoformat() if tracking.pending_option_expiry else None
        ),
        "pending_research_context": tracking.pending_research_context,
        "pending_market_context": tracking.pending_market_context,
        "pending_option_rationale": tracking.pending_option_rationale,
    }


def _tracking_from_snapshot(data: dict[str, Any]) -> _StrategyTracking:
    return _StrategyTracking(
        strategy_id=uuid.UUID(data["strategy_id"]) if data.get("strategy_id") else None,
        account_id=uuid.UUID(data["account_id"]) if data.get("account_id") else None,
        account_lookup_done=bool(data.get("account_lookup_done", False)),
        backtest_result_id=(
            uuid.UUID(data["backtest_result_id"]) if data.get("backtest_result_id") else None
        ),
        pending_option_legs=(
            [StrategyOptionLeg(**leg) for leg in data["pending_option_legs"]]
            if data.get("pending_option_legs")
            else None
        ),
        pending_option_expiry=(
            date.fromisoformat(data["pending_option_expiry"])
            if data.get("pending_option_expiry")
            else None
        ),
        pending_research_context=data.get("pending_research_context"),
        pending_market_context=data.get("pending_market_context"),
        pending_option_rationale=data.get("pending_option_rationale"),
    )


def _execute_graph_run(*, thread_id: str, root_run_id: uuid.UUID, resume: bool = False) -> None:
    """Runs in a detached `threading.Thread` (dispatched after the trigger/resume endpoint
    already returned). Synchronous end-to-end because every graph node (src/agents/nodes/*.py)
    and `graph.stream()` itself are synchronous.

    REL-060: always runs with a real Postgres-backed checkpointer (`config={"configurable":
    {"thread_id": thread_id}}`) so a pause has somewhere real to resume from -- `resume=False`
    (the normal `trigger_research` path) streams a fresh `TradingOSGraphState` as `graph.stream()`'s
    input, starting the run at its entry point exactly as before REL-060; `resume=True` (only
    ever called by `POST /agents/runs/{id}/resume`) streams `None` as the input, LangGraph's own
    documented "continue from the last checkpoint" signal, and reconstructs `_StrategyTracking`
    from the root run's own `tracking_snapshot` instead of starting a fresh one. Between each
    yielded step, the root run's real `pause_requested` flag is checked (`POST .../pause` sets
    it) -- a node can't be safely interrupted mid-execution (it could leave a half-written
    Strategy/BacktestResult row), so this is the only point a pause actually takes effect. By the
    time a step is yielded, the checkpointer has already durably saved it, confirmed by a real,
    throwaway probe against this project's own dev Postgres before this was written: pausing
    after one node and resuming with a fresh connection correctly ran only the remaining nodes."""
    redis_client = get_redis_client()
    checkpoint_wall = datetime.now(UTC)

    if resume:
        with get_session() as session:
            root = session.get(AgentRun, root_run_id)
            tracking = (
                _tracking_from_snapshot(root.tracking_snapshot)
                if root is not None and root.tracking_snapshot
                else _StrategyTracking()
            )
        stream_input: TradingOSGraphState | None = None
    else:
        stream_input = TradingOSGraphState(
            thread_id=thread_id,
            account_capital=_fetch_account_capital(),
            existing_portfolio_equity_curve=_fetch_existing_portfolio_equity_curve(),
        )
        tracking = _StrategyTracking()

    config = RunnableConfig(configurable={"thread_id": thread_id})

    try:
        with PostgresSaver.from_conn_string(runtime_checkpoint_dsn()) as checkpointer:
            graph = build_graph(checkpointer=checkpointer)
            for step in graph.stream(stream_input, config=config):
                for node_name, output in step.items():
                    # BUG-011: LangGraph's `updates` stream mode represents a node's real,
                    # intentional empty-dict return (options_strategy_node's own no-op for an
                    # Equity strategy) as `output = None`, not `{}` -- normalized once here so
                    # every downstream use (_summarize_node_output, jsonable_output,
                    # _persist_strategy_progress) sees a real, iterable dict instead of crashing
                    # on the first `.get`/`.items()`/`in`.
                    output = output or {}
                    now_wall = datetime.now(UTC)
                    AGENT_RUN_DURATION_SECONDS.labels(agent_name=node_name).observe(
                        (now_wall - checkpoint_wall).total_seconds()
                    )
                    summary = _summarize_node_output(node_name, output)

                    jsonable_output = {k: _jsonable(v) for k, v in output.items()}
                    # REL-009 E9.2 (NFR-05): the node just returned, so pop whatever run id
                    # complete() last set during its execution (None if the node made no LLM
                    # call, or tracing isn't configured) and resolve it to a real LangSmith URL
                    # before persisting.
                    langsmith_run_id = pop_last_langsmith_run_id()
                    langsmith_trace_url = (
                        fetch_langsmith_trace_url(langsmith_run_id) if langsmith_run_id else None
                    )
                    with get_session() as session:
                        child = AgentRun(
                            graph_thread_id=thread_id,
                            agent_name=node_name,
                            parent_run_id=root_run_id,
                            output_state=jsonable_output,
                            status="Completed",
                            started_at=checkpoint_wall,
                            ended_at=now_wall,
                            langsmith_trace_url=langsmith_trace_url,
                        )
                        session.add(child)
                        session.flush()
                        session.add(
                            AgentLog(
                                agent_run_id=child.id,
                                log_level="INFO",
                                message=summary,
                                created_at=now_wall,
                            )
                        )
                        _persist_strategy_progress(
                            session,
                            node_name=node_name,
                            output=output,
                            tracking=tracking,
                            agent_run_id=child.id,
                        )
                        write_audit_entry(
                            session,
                            actor_type="AI Agent",
                            actor_id=node_name,
                            action=f"GRAPH_NODE_{node_name.upper()}_COMPLETED",
                            entity_type="AgentRun",
                            entity_id=child.id,
                            after_state=jsonable_output,
                            prompt_snapshot=summary,
                        )
                        session.commit()

                    publish_agent_log(
                        redis_client,
                        json.dumps(
                            {
                                "agent_id": node_name,
                                "node": node_name,
                                "message": summary,
                                "ts": now_wall.isoformat(),
                            }
                        ),
                    )
                    checkpoint_wall = now_wall

                with get_session() as session:
                    root = session.get(AgentRun, root_run_id)
                    if root is not None and root.pause_requested:
                        root.status = "Paused"
                        root.pause_requested = False
                        root.tracking_snapshot = _tracking_to_snapshot(tracking)
                        session.commit()
                        return

        with get_session() as session:
            root = session.get(AgentRun, root_run_id)
            if root is not None:
                root.status = "Completed"
                root.ended_at = datetime.now(UTC)
                root.tracking_snapshot = None
                session.commit()
    except AgentHaltedError as exc:
        # ADR 11: a disabled node's real logic never ran -- this is a deliberate, honest stop,
        # not a failure. Recorded with its own status so the console/API never conflate the two.
        halted_ts = datetime.now(UTC)
        with get_session() as session:
            root = session.get(AgentRun, root_run_id)
            if root is not None:
                root.status = "Halted"
                root.ended_at = halted_ts
                session.add(
                    AgentLog(
                        agent_run_id=root_run_id,
                        log_level="WARNING",
                        message=str(exc),
                        created_at=halted_ts,
                    )
                )
                session.commit()
        publish_agent_log(
            redis_client,
            json.dumps(
                {
                    "agent_id": exc.agent_name,
                    "node": exc.agent_name,
                    "message": f"Run halted: {exc}",
                    "ts": halted_ts.isoformat(),
                }
            ),
        )
    except Exception as exc:  # noqa: BLE001 -- must always close out the run row, even on failure
        error_ts = datetime.now(UTC)
        with get_session() as session:
            root = session.get(AgentRun, root_run_id)
            if root is not None:
                root.status = "Failed"
                root.ended_at = error_ts
                session.add(
                    AgentLog(
                        agent_run_id=root_run_id,
                        log_level="ERROR",
                        message=str(exc),
                        created_at=error_ts,
                    )
                )
                session.commit()
        publish_agent_log(
            redis_client,
            json.dumps(
                {
                    "agent_id": GRAPH_ROOT_AGENT_NAME,
                    "node": GRAPH_ROOT_AGENT_NAME,
                    "message": f"Run failed: {exc}",
                    "ts": error_ts.isoformat(),
                }
            ),
        )
    finally:
        redis_client.close()


@dataclass
class _SuggestionRegenTracking:
    """REL-048: the suggestion-regeneration analogue of `_StrategyTracking` above, deliberately
    smaller -- `strategy_id` is known up front (the suggestion already names an existing
    Strategy), so there is no "has strategy_generator fired yet" gate to thread, and no
    account/research-context staging (both are seeded into `TradingOSGraphState` once, before
    the graph even starts, from the target strategy's own already-persisted REL-044 columns)."""

    strategy_id: uuid.UUID
    backtest_result_id: uuid.UUID | None = None
    new_version_id: uuid.UUID | None = None
    pending_option_legs: list[StrategyOptionLeg] | None = None
    pending_option_expiry: date | None = None
    pending_option_rationale: str | None = None


def _persist_suggestion_regeneration(
    session: Session,
    *,
    node_name: str,
    output: dict[str, Any],
    tracking: _SuggestionRegenTracking,
) -> None:
    """REL-048. Deliberately NOT `_persist_strategy_progress` above -- that function's own
    `strategy_generator` branch unconditionally creates a brand-new `Strategy` row every time it
    fires, which is correct for the main graph (each real run proposes a genuinely new idea) but
    wrong here: a suggestion regenerates an EXISTING strategy, so this updates that strategy's own
    logic columns in place instead. Every other branch mirrors `_persist_strategy_progress`
    exactly, scoped to the one known `tracking.strategy_id`."""
    if node_name == "strategy_generator" and "strategy_logic" in output:
        logic = output["strategy_logic"]
        strategy_row = session.get(Strategy, tracking.strategy_id)
        if strategy_row is not None:
            strategy_row.hypothesis = logic.hypothesis
            strategy_row.asset_class = logic.asset_class
            strategy_row.style = logic.style
            strategy_row.universe = logic.universe or None
            strategy_row.entry_conditions = logic.entry_conditions
            strategy_row.exit_conditions = logic.exit_conditions
            strategy_row.stop_loss = logic.stop_loss
            strategy_row.take_profit = logic.take_profit
            strategy_row.position_sizing = logic.position_sizing
            strategy_row.confidence_score = logic.confidence_score
        return

    # BUG-011: see the identical guard + full explanation in `_persist_strategy_progress` above.
    if node_name == "options_strategy_agent" and output and "strategy_logic" in output:
        tracking.pending_option_legs = output["strategy_logic"].option_legs
        tracking.pending_option_expiry = output.get("option_expiry")
        tracking.pending_option_rationale = output.get("option_rationale")
        return

    if node_name == "python_code_generator" and "python_code" in output:
        code = output["python_code"]
        version = StrategyVersion(
            strategy_id=tracking.strategy_id,
            version_no=code.version_no,
            python_code=code.code,
            validation_status="Pending",
            option_legs=(
                [leg.model_dump() for leg in tracking.pending_option_legs]
                if tracking.pending_option_legs
                else None
            ),
            option_expiry=tracking.pending_option_expiry,
            option_rationale=tracking.pending_option_rationale,
        )
        session.add(version)
        session.flush()
        tracking.new_version_id = version.id
        strategy_row = session.get(Strategy, tracking.strategy_id)
        if strategy_row is not None:
            strategy_row.current_version_id = version.id
            strategy_row.status = "Coding"
        return

    if node_name == "python_validator" and "validation_result" in output:
        strategy_row = session.get(Strategy, tracking.strategy_id)
        if strategy_row is None or strategy_row.current_version_id is None:
            return
        if output["validation_result"].status != "Pass":
            return  # a retry produces a new StrategyVersion via the branch above
        version_row = session.get(StrategyVersion, strategy_row.current_version_id)
        if version_row is None:
            return
        run_strategy_factory_pipeline(
            version_row.python_code, strategy_version_id=str(version_row.id)
        )
        strategy_row.status = "Backtesting"
        return

    if node_name == "backtesting" and "backtest_metrics" in output:
        strategy_row = session.get(Strategy, tracking.strategy_id)
        if (
            strategy_row is None
            or strategy_row.current_version_id is None
            or not strategy_row.universe
        ):
            return
        lake = DataLake(get_settings().data_lake_root / "ohlcv_daily")
        date_to = lake.latest_date(strategy_row.universe[0])
        if date_to is None:
            return
        metrics = output["backtest_metrics"]
        result = BacktestResult(
            strategy_version_id=strategy_row.current_version_id,
            date_from=date_to - timedelta(days=DEFAULT_BACKTEST_LOOKBACK_DAYS),
            date_to=date_to,
            initial_capital=DEFAULT_INITIAL_CAPITAL,
            symbol=strategy_row.universe[0],
            sharpe_ratio=metrics.sharpe_ratio,
            sortino_ratio=metrics.sortino_ratio,
            calmar_ratio=metrics.calmar_ratio,
            max_drawdown=metrics.max_drawdown,
            cagr=metrics.cagr,
            win_rate=metrics.win_rate,
            profit_factor=metrics.profit_factor,
            expectancy=metrics.expectancy,
            total_trades=metrics.total_trades,
            data_adjusted=metrics.data_adjusted,
            provider_used=metrics.provider_used,
            data_retrieved_at=metrics.data_retrieved_at,
        )
        session.add(result)
        session.flush()
        tracking.backtest_result_id = result.id
        return

    if tracking.backtest_result_id is None:
        return

    if node_name == "evaluator" and "evaluation_verdict" in output:
        result_row = session.get(BacktestResult, tracking.backtest_result_id)
        verdict = output["evaluation_verdict"]
        if result_row is not None:
            result_row.evaluation_verdict = verdict.verdict
            result_row.evaluation_failure_reasons = verdict.failure_reasons or None
        # No status change here -- python_validator's own branch above already moved the
        # strategy to "Backtesting" the moment a real BacktestResult exists to review; a human
        # decides PaperTrading/Live promotion via the existing /promote endpoint regardless of
        # PASS/FAIL, matching every other regeneration this codebase produces.
        return


def run_suggestion_regeneration(*, suggestion_id: uuid.UUID) -> None:
    """REL-048: background job for `POST /strategies/{id}/suggestions/{suggestion_id}/review`
    (`src/api/routers/strategies.py`). Runs the lightweight Suggestion Reviewer Agent first
    (`src/agents/nodes/suggestion_reviewer.py`); only if it judges the suggestion sound does this
    re-enter the real agent pipeline via `build_suggestion_regeneration_graph()`
    (`src/agents/graph.py`), seeded with a synthetic FAIL `EvaluationVerdict` carrying the
    suggestion text as `feedback_for_strategy_generator` -- the exact mechanism the Evaluator's
    own real FAIL-retry loop already proves works, see `strategy_generator_node`'s own docstring.
    `status` ends `Applied` only if the pipeline actually produced a new `StrategyVersion`
    (`tracking.new_version_id is not None`) -- a `sound=True` verdict followed by a pipeline that
    never got there (Compliance blocked it, code validation exhausted its retries, or a node
    halted/crashed) still leaves the suggestion `Rejected`, since "Applied" would otherwise claim
    a version that doesn't exist."""
    redis_client = get_redis_client()
    with get_session() as session:
        suggestion = session.get(StrategySuggestion, suggestion_id)
        if suggestion is None:
            redis_client.close()
            return
        strategy = session.get(Strategy, suggestion.strategy_id)
        if strategy is None:
            suggestion.status = "Rejected"
            suggestion.ai_reasoning = (
                "The strategy this suggestion was submitted against no longer exists."
            )
            suggestion.reviewed_at = datetime.now(UTC)
            session.commit()
            redis_client.close()
            return

        suggestion.status = "Reviewing"
        strategy_logic_summary: dict[str, object] = {
            "hypothesis": strategy.hypothesis,
            "asset_class": strategy.asset_class,
            "style": strategy.style,
            "entry_conditions": strategy.entry_conditions,
            "exit_conditions": strategy.exit_conditions,
            "stop_loss": strategy.stop_loss,
            "take_profit": strategy.take_profit,
            "position_sizing": strategy.position_sizing,
            "confidence_score": (
                float(strategy.confidence_score) if strategy.confidence_score is not None else None
            ),
        }
        latest_result = session.execute(
            select(BacktestResult)
            .join(StrategyVersion, StrategyVersion.id == BacktestResult.strategy_version_id)
            .where(StrategyVersion.strategy_id == strategy.id)
            .order_by(BacktestResult.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        backtest_verdict_summary: dict[str, object] | None = (
            {
                "evaluation_verdict": latest_result.evaluation_verdict,
                "sharpe_ratio": (
                    float(latest_result.sharpe_ratio)
                    if latest_result.sharpe_ratio is not None
                    else None
                ),
                "max_drawdown": (
                    float(latest_result.max_drawdown)
                    if latest_result.max_drawdown is not None
                    else None
                ),
                "deployment_recommendation": latest_result.deployment_recommendation,
            }
            if latest_result is not None
            else None
        )
        research_context = strategy.research_context
        market_context = strategy.market_context
        suggestion_text = suggestion.suggestion_text
        strategy_id = strategy.id
        # BUG-012: python_code_generator_node computes the next version_no purely from
        # `state.python_code.version_no + 1` (defaulting to 1 when state.python_code is None) --
        # correct for the main graph, where a fresh thread genuinely starts at v1, but wrong here,
        # where the target strategy already has real versions in the DB. Left unseeded, this
        # collides with the real `UniqueConstraint("strategy_id", "version_no")` on every
        # strategy whose latest version isn't v0. Found the same live-testing pass as BUG-011.
        latest_version_no = (
            session.execute(
                select(StrategyVersion.version_no)
                .where(StrategyVersion.strategy_id == strategy_id)
                .order_by(StrategyVersion.version_no.desc())
                .limit(1)
            ).scalar_one_or_none()
            or 0
        )
        session.commit()

    try:
        verdict = review_suggestion(
            strategy_logic_summary, backtest_verdict_summary, suggestion_text
        )
    except Exception as exc:  # noqa: BLE001 -- a review failure must still resolve the suggestion
        logger.warning(
            "suggestion_review_llm_failed", error=str(exc), suggestion_id=str(suggestion_id)
        )
        with get_session() as session:
            suggestion = session.get(StrategySuggestion, suggestion_id)
            if suggestion is not None:
                suggestion.status = "Rejected"
                suggestion.ai_verdict = "Review failed"
                suggestion.ai_reasoning = f"The review step itself failed: {exc}"
                suggestion.reviewed_at = datetime.now(UTC)
                session.commit()
        redis_client.close()
        return

    with get_session() as session:
        suggestion = session.get(StrategySuggestion, suggestion_id)
        if suggestion is None:
            redis_client.close()
            return
        suggestion.ai_verdict = "Sound" if verdict.sound else "Not sound"
        suggestion.ai_reasoning = verdict.reasoning
        if not verdict.sound:
            suggestion.status = "Rejected"
            suggestion.reviewed_at = datetime.now(UTC)
            session.commit()
            redis_client.close()
            return
        session.commit()

    # Sound -- re-enter the real pipeline to produce a genuine new candidate version.
    thread_id = str(uuid.uuid4())
    started_at = datetime.now(UTC)
    with get_session() as session:
        root = AgentRun(
            graph_thread_id=thread_id,
            agent_name="SuggestionRegeneration",
            status="Running",
            started_at=started_at,
        )
        session.add(root)
        session.commit()
        root_run_id = root.id

    reconstructed_directive: ResearchDirective | None = None
    reconstructed_context: MarketContext | None = None
    try:
        if research_context:
            reconstructed_directive = ResearchDirective.model_validate(research_context)
        if market_context:
            reconstructed_context = MarketContext.model_validate(market_context)
    except Exception as exc:  # noqa: BLE001 -- proceed without context rather than fail the run
        logger.warning("suggestion_regen_context_reconstruction_failed", error=str(exc))

    graph = build_suggestion_regeneration_graph()
    state = TradingOSGraphState(
        thread_id=thread_id,
        research_directive=reconstructed_directive,
        market_context=reconstructed_context,
        account_capital=_fetch_account_capital(),
        existing_portfolio_equity_curve=_fetch_existing_portfolio_equity_curve(),
        # BUG-012 (see above): seeds python_code_generator_node's own `version_no + 1` derivation
        # with the real latest version already on this strategy, not a fabricated code body --
        # `code=""` is never read for this, only `.version_no` is.
        python_code=PythonCode(code="", version_no=latest_version_no),
        evaluation_verdict=EvaluationVerdict(
            verdict="FAIL",
            failure_reasons=["User-submitted suggestion"],
            feedback_for_strategy_generator=suggestion_text,
        ),
    )
    checkpoint_wall = datetime.now(UTC)
    tracking = _SuggestionRegenTracking(strategy_id=strategy_id)

    try:
        for step in graph.stream(state):
            for node_name, output in step.items():
                # BUG-011: see the identical guard + full explanation in `_execute_graph_run` above.
                output = output or {}
                now_wall = datetime.now(UTC)
                AGENT_RUN_DURATION_SECONDS.labels(agent_name=node_name).observe(
                    (now_wall - checkpoint_wall).total_seconds()
                )
                summary = _summarize_node_output(node_name, output)
                jsonable_output = {k: _jsonable(v) for k, v in output.items()}
                langsmith_run_id = pop_last_langsmith_run_id()
                langsmith_trace_url = (
                    fetch_langsmith_trace_url(langsmith_run_id) if langsmith_run_id else None
                )
                with get_session() as session:
                    child = AgentRun(
                        graph_thread_id=thread_id,
                        agent_name=node_name,
                        parent_run_id=root_run_id,
                        output_state=jsonable_output,
                        status="Completed",
                        started_at=checkpoint_wall,
                        ended_at=now_wall,
                        langsmith_trace_url=langsmith_trace_url,
                    )
                    session.add(child)
                    session.flush()
                    session.add(
                        AgentLog(
                            agent_run_id=child.id,
                            log_level="INFO",
                            message=summary,
                            created_at=now_wall,
                        )
                    )
                    _persist_suggestion_regeneration(
                        session, node_name=node_name, output=output, tracking=tracking
                    )
                    session.commit()
                publish_agent_log(
                    redis_client,
                    json.dumps(
                        {
                            "agent_id": node_name,
                            "node": node_name,
                            "message": summary,
                            "ts": now_wall.isoformat(),
                        }
                    ),
                )
                checkpoint_wall = now_wall

        with get_session() as session:
            root_run = session.get(AgentRun, root_run_id)
            if root_run is not None:
                root_run.status = "Completed"
                root_run.ended_at = datetime.now(UTC)
            suggestion = session.get(StrategySuggestion, suggestion_id)
            if suggestion is not None:
                if tracking.new_version_id is not None:
                    suggestion.status = "Applied"
                    suggestion.resulting_version_id = tracking.new_version_id
                else:
                    suggestion.status = "Rejected"
                    suggestion.ai_reasoning = (
                        f"{suggestion.ai_reasoning} (The regeneration pipeline judged the "
                        "suggestion sound but did not produce a passing version -- see this "
                        "run's own Agent Console history for why.)"
                    )
                suggestion.reviewed_at = datetime.now(UTC)
            session.commit()
    except AgentHaltedError as exc:
        halted_ts = datetime.now(UTC)
        with get_session() as session:
            root_run = session.get(AgentRun, root_run_id)
            if root_run is not None:
                root_run.status = "Halted"
                root_run.ended_at = halted_ts
                session.add(
                    AgentLog(
                        agent_run_id=root_run_id,
                        log_level="WARNING",
                        message=str(exc),
                        created_at=halted_ts,
                    )
                )
            suggestion = session.get(StrategySuggestion, suggestion_id)
            if suggestion is not None:
                suggestion.status = "Rejected"
                suggestion.ai_reasoning = (
                    f"{suggestion.ai_reasoning} (Regeneration run halted: {exc})"
                )
                suggestion.reviewed_at = halted_ts
            session.commit()
    except Exception as exc:  # noqa: BLE001 -- must always resolve the suggestion, even on failure
        error_ts = datetime.now(UTC)
        with get_session() as session:
            root_run = session.get(AgentRun, root_run_id)
            if root_run is not None:
                root_run.status = "Failed"
                root_run.ended_at = error_ts
                session.add(
                    AgentLog(
                        agent_run_id=root_run_id,
                        log_level="ERROR",
                        message=str(exc),
                        created_at=error_ts,
                    )
                )
            suggestion = session.get(StrategySuggestion, suggestion_id)
            if suggestion is not None:
                suggestion.status = "Rejected"
                suggestion.ai_reasoning = (
                    f"{suggestion.ai_reasoning} (Regeneration run failed: {exc})"
                )
                suggestion.reviewed_at = error_ts
            session.commit()
    finally:
        redis_client.close()


@router.post("/research/trigger", response_model=TriggerResponse, status_code=202)
def trigger_research(_user: User = Depends(_can_manage_hitl)) -> TriggerResponse:
    """Starts one real end-to-end graph run (CEO -> Market Analyst -> Strategy Generator ->
    Code Gen -> Validator loop). Every node makes a real LLM call through
    src/agents/llm_router.py against whichever provider is configured -- this is not a dry run.

    REL-011 E10.11.0: found with NO auth dependency at all during frontend-completeness
    research -- any caller, including unauthenticated ones, could kick off a real,
    LLM-costing graph run. Gated to the same SA/PM/RM set as the Orchestrator HITL endpoints
    below, since triggering the research pipeline is an equivalent-weight operational action.

    Dispatched via a detached `threading.Thread`, not FastAPI's `BackgroundTasks`: Starlette
    awaits every registered BackgroundTask during graceful shutdown, and a single node here can
    take up to the LLM client's timeout (Ollama's fallback path alone can run ~600s). With
    `--reload` that meant editing any file blocked the dev server from restarting until the
    in-flight LLM call finished or timed out -- confirmed by hand, it once stalled a reload for
    ~10 minutes. A daemon thread isn't tracked by Starlette's shutdown sequence, so `--reload`
    (and `docker compose restart`) return immediately; the run keeps executing and still writes
    its AgentRun/AgentLog rows for whoever's watching, it just isn't graceful if the process
    exits mid-run -- acceptable for this dev-only trigger endpoint."""
    thread_id = str(uuid.uuid4())
    started_at = datetime.now(UTC)

    with get_session() as session:
        root = AgentRun(
            graph_thread_id=thread_id,
            agent_name=GRAPH_ROOT_AGENT_NAME,
            status="Running",
            started_at=started_at,
        )
        session.add(root)
        session.commit()
        run_id = root.id

    threading.Thread(
        target=_execute_graph_run,
        kwargs={"thread_id": thread_id, "root_run_id": run_id},
        daemon=True,
    ).start()
    return TriggerResponse(run_id=run_id, thread_id=thread_id, status="Running")


# --- Pause/Resume (REL-060, API-020/021) ---------------------------------------------------


def _get_root_run(session: Session, run_id: uuid.UUID) -> AgentRun | None:
    root = session.get(AgentRun, run_id)
    if root is None or root.parent_run_id is not None:
        return None  # a per-node child row is not a pausable/resumable run in its own right
    return root


@router.post("/runs/{run_id}/pause", response_model=TriggerResponse)
def pause_run(run_id: uuid.UUID, _user: User = Depends(_can_manage_hitl)) -> TriggerResponse:
    """API-020. Sets a real, DB-backed signal on the root run -- `_execute_graph_run`'s
    background thread checks it between graph steps and stops there, the only point a node
    can be safely interrupted (mid-execution risks a half-written Strategy/BacktestResult row).
    The status flip to "Paused" happens asynchronously, once the thread actually reaches that
    checkpoint -- this endpoint returns immediately with the run still "Running" and the
    request recorded."""
    with get_session() as session:
        root = _get_root_run(session, run_id)
        if root is None:
            raise HTTPException(status_code=404, detail="Run not found")
        if root.status != "Running":
            raise HTTPException(
                status_code=400, detail=f"Run status is '{root.status}', not 'Running'"
            )
        root.pause_requested = True
        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=str(_user.id),
            action="GRAPH_RUN_PAUSE_REQUESTED",
            entity_type="AgentRun",
            entity_id=root.id,
        )
        session.commit()
        return TriggerResponse(run_id=root.id, thread_id=root.graph_thread_id, status=root.status)


@router.post("/runs/{run_id}/resume", response_model=TriggerResponse, status_code=202)
def resume_run(run_id: uuid.UUID, _user: User = Depends(_can_manage_hitl)) -> TriggerResponse:
    """API-021. Only valid from a real "Paused" run -- one that stopped between graph steps with
    the real LangGraph checkpointer already holding its exact execution position (confirmed via
    a real probe against this project's own dev Postgres before this was built: a fresh
    connection resuming a paused run re-ran only the nodes that hadn't completed yet, never the
    ones already done). Dispatches a new background thread,
    `_execute_graph_run(..., resume=True)`."""
    with get_session() as session:
        root = _get_root_run(session, run_id)
        if root is None:
            raise HTTPException(status_code=404, detail="Run not found")
        if root.status != "Paused":
            raise HTTPException(
                status_code=400, detail=f"Run status is '{root.status}', not 'Paused'"
            )
        root.status = "Running"
        thread_id = root.graph_thread_id
        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=str(_user.id),
            action="GRAPH_RUN_RESUMED",
            entity_type="AgentRun",
            entity_id=root.id,
        )
        session.commit()

    threading.Thread(
        target=_execute_graph_run,
        kwargs={"thread_id": thread_id, "root_run_id": run_id, "resume": True},
        daemon=True,
    ).start()
    return TriggerResponse(run_id=run_id, thread_id=thread_id, status="Running")


# --- Run history ------------------------------------------------------------------------------


class AgentLogEntry(BaseModel):
    node: str
    log_level: str
    message: str
    created_at: datetime


class AgentRunSummary(BaseModel):
    run_id: uuid.UUID
    thread_id: str
    agent_name: str
    status: str
    started_at: datetime
    ended_at: datetime | None
    # REL-011 E11.4b: AgentRun.human_decision (REL-010 E10.8d) was never serialized onto this
    # response model -- only HitlDecisionResponse (the approve/reject mutation's own return
    # value) carried it, so a reloaded run detail view had no way to show "already
    # approved/rejected" state. Additive field, not a new mutation.
    human_decision: str | None = None
    # REL-062 (API-073): AgentRun.langsmith_trace_url has been real and persisted since REL-009
    # E9.2 (_execute_graph_run resolves it via fetch_langsmith_trace_url() on every node), but
    # was never serialized by this response model -- confirmed by direct grep before writing
    # this. None whenever tracing wasn't configured, or the node made no LLM call, honest either
    # way, not a missing feature.
    langsmith_trace_url: str | None = None


class AgentRunDetail(AgentRunSummary):
    nodes: list[AgentRunSummary]
    logs: list[AgentLogEntry]


def _to_summary(run: AgentRun) -> AgentRunSummary:
    return AgentRunSummary(
        run_id=run.id,
        thread_id=run.graph_thread_id,
        agent_name=run.agent_name,
        status=run.status,
        started_at=run.started_at,
        ended_at=run.ended_at,
        human_decision=run.human_decision,
        langsmith_trace_url=run.langsmith_trace_url,
    )


@router.get("/runs", response_model=list[AgentRunSummary])
def list_runs() -> list[AgentRunSummary]:
    """Root runs of the main strategy-generation graph specifically -- REL-008 added its own
    separate root-level AgentRun rows for `/ml/models/train`/`/ml/rl/train` dispatches (also
    `parent_run_id IS NULL`, since they're independent small graphs, not children of this one),
    so `parent_run_id IS NULL` alone is no longer a correct proxy for "a TradingOSGraph run" --
    this endpoint's own real contract (confirmed by its pre-existing test) is scoped to this
    graph, not "every kind of root-level orchestration run" in the ledger."""
    with get_session() as session:
        roots = session.scalars(
            select(AgentRun)
            .where(
                AgentRun.parent_run_id.is_(None),
                AgentRun.agent_name == GRAPH_ROOT_AGENT_NAME,
            )
            .order_by(AgentRun.started_at.desc())
            .limit(20)
        )
        return [_to_summary(r) for r in roots]


@router.get("/runs/{run_id}", response_model=AgentRunDetail)
def get_run(run_id: uuid.UUID) -> AgentRunDetail:
    """Logs are attached to each per-node child AgentRun (see `_execute_graph_run`), not the
    root -- so the Thought Stream needs logs from the root run itself plus every child node,
    merged in chronological order, not just `AgentLog.agent_run_id == run_id`."""
    with get_session() as session:
        root = session.get(AgentRun, run_id)
        if root is None:
            raise HTTPException(status_code=404, detail="Run not found")
        children = list(
            session.scalars(
                select(AgentRun)
                .where(AgentRun.parent_run_id == run_id)
                .order_by(AgentRun.started_at)
            )
        )
        run_ids_by_agent = {run_id: root.agent_name, **{c.id: c.agent_name for c in children}}
        logs = session.scalars(
            select(AgentLog)
            .where(AgentLog.agent_run_id.in_(run_ids_by_agent.keys()))
            .order_by(AgentLog.created_at)
        )
        return AgentRunDetail(
            **_to_summary(root).model_dump(),
            nodes=[_to_summary(c) for c in children],
            logs=[
                AgentLogEntry(
                    node=run_ids_by_agent[log.agent_run_id],
                    log_level=log.log_level,
                    message=log.message,
                    created_at=log.created_at,
                )
                for log in logs
            ],
        )


# --- Agent Monitoring Analytics (REL-068, API-157..158) ---------------------------------------


class AgentAnalyticsSummaryRow(BaseModel):
    agent_name: str
    display_name: str
    total_runs: int
    completed: int
    failed: int
    running: int
    success_rate: float | None
    avg_duration_seconds: float | None
    p50_duration_seconds: float | None
    p95_duration_seconds: float | None


@router.get("/analytics/summary", response_model=list[AgentAnalyticsSummaryRow])
def get_analytics_summary(days: int = 30) -> list[AgentAnalyticsSummaryRow]:
    """REL-068. Real per-agent execution stats over the real ledger (AgentRun) -- every root
    graph run AND every per-node child run, not just the root-only rows GET /runs returns. The
    real aggregation math (success rate, Python-side duration percentiles matching
    `src.engine.optimization.monte_carlo`'s own established convention) lives in
    `src.agents.analytics`, independently unit-tested against fixture data."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    display_names = {a.name: a.display_name for a in KNOWN_AGENTS}

    with get_session() as session:
        rows = session.execute(
            select(
                AgentRun.agent_name, AgentRun.status, AgentRun.started_at, AgentRun.ended_at
            ).where(AgentRun.started_at >= cutoff)
        ).all()

    by_agent = group_by_agent([tuple(row) for row in rows])
    result: list[AgentAnalyticsSummaryRow] = []
    for agent_name, entries in sorted(by_agent.items()):
        stats = summarize_runs(entries)
        result.append(
            AgentAnalyticsSummaryRow(
                agent_name=agent_name,
                display_name=display_names.get(agent_name, agent_name),
                total_runs=stats.total_runs,
                completed=stats.completed,
                failed=stats.failed,
                running=stats.running,
                success_rate=stats.success_rate,
                avg_duration_seconds=stats.avg_duration_seconds,
                p50_duration_seconds=stats.p50_duration_seconds,
                p95_duration_seconds=stats.p95_duration_seconds,
            )
        )
    return result


class AgentAnalyticsTrendPoint(BaseModel):
    date: date
    total_runs: int
    completed: int
    failed: int


@router.get("/analytics/trend", response_model=list[AgentAnalyticsTrendPoint])
def get_analytics_trend(days: int = 30) -> list[AgentAnalyticsTrendPoint]:
    """REL-068. Real daily run-volume trend across every AgentRun row (root graph runs and every
    per-node child run) in the window -- genuine day-by-day execution activity across the whole
    system, not narrowly scoped to one graph type (this ledger already has more than one real
    root-level graph -- TradingOSGraph, SuggestionRegeneration, and independent ML-training
    dispatches -- so an all-rows view is the honest "how busy was the system" answer, not one
    graph's own subset). Only real days with at least 1 run are returned -- never a zero-filled
    synthetic day. Bucketing logic lives in `src.agents.analytics`, independently unit-tested."""
    cutoff = datetime.now(UTC) - timedelta(days=days)

    with get_session() as session:
        rows = session.execute(
            select(AgentRun.status, AgentRun.started_at).where(AgentRun.started_at >= cutoff)
        ).all()

    buckets = bucket_by_day([tuple(row) for row in rows])
    return [
        AgentAnalyticsTrendPoint(
            date=b.date, total_runs=b.total_runs, completed=b.completed, failed=b.failed
        )
        for b in buckets
    ]


# --- Orchestrator HITL (REL-010 E10.8d, API-020..024) -----------------------------------------


class RetryResponse(BaseModel):
    run_id: uuid.UUID
    retried_from_run_id: uuid.UUID
    thread_id: str
    status: str


@router.post("/runs/{run_id}/retry", response_model=RetryResponse, status_code=202)
def retry_run(run_id: uuid.UUID, _user: User = Depends(_can_manage_hitl)) -> RetryResponse:
    """API-024 (previously mislabeled "API-021" here, which is actually
    `/orchestrator/runs/{run_id}/resume`, still No -- see approve_run()'s note on why no
    pause/resume state machine exists). Valid only for a run that genuinely ended `"Failed"` --
    dispatches a fresh end-to-end graph run via the same detached-thread machinery as
    `/research/trigger`, with `retried_from_run_id` linking it back to the run a human asked to
    retry."""
    with get_session() as session:
        failed = session.get(AgentRun, run_id)
        if failed is None:
            raise HTTPException(status_code=404, detail="Run not found")
        if failed.status != "Failed":
            raise HTTPException(
                status_code=400, detail=f"Run status is '{failed.status}', not 'Failed'"
            )

        thread_id = str(uuid.uuid4())
        root = AgentRun(
            graph_thread_id=thread_id,
            agent_name=GRAPH_ROOT_AGENT_NAME,
            status="Running",
            started_at=datetime.now(UTC),
            retried_from_run_id=run_id,
        )
        session.add(root)
        session.commit()
        new_run_id = root.id

    threading.Thread(
        target=_execute_graph_run,
        kwargs={"thread_id": thread_id, "root_run_id": new_run_id},
        daemon=True,
    ).start()
    return RetryResponse(
        run_id=new_run_id, retried_from_run_id=run_id, thread_id=thread_id, status="Running"
    )


def _strategy_from_run_lineage(session: Session, run_id: uuid.UUID) -> Strategy | None:
    """Walks the real DB-012 lineage from a root AgentRun to whichever Strategy its graph thread
    produced the most recent BacktestResult for. BacktestResult.agent_run_id points at the
    "backtesting" node's own per-node child AgentRun (see `_persist_strategy_progress` above),
    not the root run -- so this looks up that child first, rather than assuming `run_id` itself
    is what BacktestResult references."""
    backtesting_run_ids = list(
        session.scalars(
            select(AgentRun.id).where(
                AgentRun.parent_run_id == run_id, AgentRun.agent_name == "backtesting"
            )
        )
    )
    if not backtesting_run_ids:
        return None
    result = session.scalars(
        select(BacktestResult)
        .where(BacktestResult.agent_run_id.in_(backtesting_run_ids))
        .order_by(BacktestResult.created_at.desc())
    ).first()
    if result is None:
        return None
    version = session.get(StrategyVersion, result.strategy_version_id)
    if version is None:
        return None
    return session.get(Strategy, version.strategy_id)


class HitlDecisionResponse(BaseModel):
    run_id: uuid.UUID
    human_decision: str
    strategy_id: uuid.UUID | None = None
    strategy_status: str | None = None


@router.post("/runs/{run_id}/approve", response_model=HitlDecisionResponse)
def approve_run(run_id: uuid.UUID, _user: User = Depends(_can_manage_hitl)) -> HitlDecisionResponse:
    """API-022. Records a human's real, audited sign-off on this run's deployment
    recommendation. No further state change: an auto-`"PaperTrading"` recommendation was already
    applied by `_persist_strategy_progress` when the run completed -- there is no mid-graph pause
    state machine to resume (no such feature exists in this pipeline), so approval here is a
    durable record of agreement, not a trigger."""
    with get_session() as session:
        run = session.get(AgentRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        run.human_decision = "Approved"
        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=_user.email,
            action="AGENT_RUN_APPROVED",
            entity_type="AgentRun",
            entity_id=run_id,
            after_state={"human_decision": "Approved"},
        )
        session.commit()
        return HitlDecisionResponse(run_id=run_id, human_decision="Approved")


class RejectRunRequest(BaseModel):
    reason: str


@router.post("/runs/{run_id}/reject", response_model=HitlDecisionResponse)
def reject_run(
    run_id: uuid.UUID, body: RejectRunRequest, _user: User = Depends(_can_manage_hitl)
) -> HitlDecisionResponse:
    """API-023. The real human-override mechanism (Business Rule 3): if this run's thread
    produced a Strategy that reached `"PaperTrading"` automatically, a reject overrides it to
    `"Deprecated"` -- a required `reason` is captured in the audit trail, never silently
    dropped."""
    with get_session() as session:
        run = session.get(AgentRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        run.human_decision = "Rejected"

        strategy = _strategy_from_run_lineage(session, run_id)
        strategy_status = None
        if strategy is not None and strategy.status == "PaperTrading":
            strategy.status = "Deprecated"
            strategy_status = strategy.status

        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=_user.email,
            action="AGENT_RUN_REJECTED",
            entity_type="AgentRun",
            entity_id=run_id,
            after_state={
                "human_decision": "Rejected",
                "reason": body.reason,
                "strategy_id": str(strategy.id) if strategy is not None else None,
                "strategy_status": strategy_status,
            },
        )
        session.commit()
        return HitlDecisionResponse(
            run_id=run_id,
            human_decision="Rejected",
            strategy_id=strategy.id if strategy is not None else None,
            strategy_status=strategy_status,
        )


# --- Prompt registry (Prompt Management Interface) -------------------------------------------


class PromptSummary(BaseModel):
    agent_slug: str
    prompt_id: str
    active_version: int
    available_versions: list[int]


class PromptVersionContent(BaseModel):
    agent_slug: str
    version: int
    content: str


class SetActiveVersionRequest(BaseModel):
    version: int


@router.get("/prompts", response_model=list[PromptSummary])
def list_prompts() -> list[PromptSummary]:
    manifest = prompt_registry.list_agents()
    return [
        PromptSummary(
            agent_slug=slug,
            prompt_id=entry["prompt_id"],
            active_version=entry["active_version"],
            available_versions=prompt_registry.list_versions(slug),
        )
        for slug, entry in manifest.items()
    ]


@router.get("/prompts/{slug}/versions/{version}", response_model=PromptVersionContent)
def get_prompt_version(slug: str, version: int) -> PromptVersionContent:
    try:
        content = prompt_registry.get_prompt_version(slug, version)
    except PromptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PromptVersionContent(agent_slug=slug, version=version, content=content)


@router.put("/prompts/{slug}/active-version", response_model=PromptSummary)
def set_active_version(
    slug: str, body: SetActiveVersionRequest, _user: User = Depends(_can_manage_hitl)
) -> PromptSummary:
    """REL-011 E10.11.0: found with NO auth dependency at all -- any caller could hot-swap
    which prompt version drives a production agent. Gated to the same SA/PM/RM set as the
    Orchestrator HITL endpoints, since this is an equivalent-weight operational action."""
    try:
        prompt_registry.set_active_version(slug, body.version)
    except PromptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    manifest = prompt_registry.list_agents()
    entry = manifest[slug]
    return PromptSummary(
        agent_slug=slug,
        prompt_id=entry["prompt_id"],
        active_version=entry["active_version"],
        available_versions=prompt_registry.list_versions(slug),
    )


# --- Agent detail (API-026) -----------------------------------------------------------------
#
# REL-062: registered at the very end of this router, after every other route above, so this
# single dynamic `/{agent_id}` segment can never shadow an existing literal route (`/graph`,
# `/control`, `/runs`, `/prompts`, ...) registered earlier -- the same route-ordering discipline
# this session already applied once before, in orders.py.


class AgentSkillGrant(BaseModel):
    skill_name: str
    granted_at: datetime


class AgentInstanceDetail(BaseModel):
    name: str
    display_name: str
    kind: str
    enforced: bool
    enabled: bool
    disabled_reason: str | None
    skills: list[AgentSkillGrant]
    last_run_status: str | None
    last_run_at: datetime | None


class AgentDetailResponse(BaseModel):
    agent_id: str
    instances: list[AgentInstanceDetail]


@router.get("/{agent_id}", response_model=AgentDetailResponse)
def get_agent_detail(agent_id: str) -> AgentDetailResponse:
    """API-026. `agent_id` is the SRS's own identifier (e.g. "AGT-001"), not KNOWN_AGENTS'
    internal `name` that `/control/{agent_name}` above keys on. One real quirk in the registry,
    confirmed by direct read of control.py rather than assumed: AGT-009 is shared by two distinct
    implementations -- `memory_ingest` (the graph-node incarnation) and `memory_agent` (the
    scheduled one). `instances` is a list rather than a single object so this stays honest about
    that instead of silently picking one. `last_run_status`/`last_run_at` come from the most
    recent AgentRun row for that instance's `name` -- deliberately not called "current_task",
    since most of these agents aren't graph nodes and nothing in this codebase tracks real-time
    task state for them."""
    matches = [a for a in KNOWN_AGENTS if a.agent_id == agent_id]
    if not matches:
        raise HTTPException(status_code=404, detail=f"Unknown agent_id '{agent_id}'")
    with get_session() as session:
        control_rows = {row.agent_name: row for row in session.scalars(select(AgentControlState))}
        instances = []
        for agent in matches:
            control_row = control_rows.get(agent.name)
            grants = session.execute(
                select(AgentSkillMap, Skill.name)
                .join(Skill, AgentSkillMap.skill_id == Skill.id)
                .where(AgentSkillMap.agent_name == agent.name)
            ).all()
            last_run = session.scalars(
                select(AgentRun)
                .where(AgentRun.agent_name == agent.name)
                .order_by(AgentRun.started_at.desc())
                .limit(1)
            ).first()
            instances.append(
                AgentInstanceDetail(
                    name=agent.name,
                    display_name=agent.display_name,
                    kind=agent.kind,
                    enforced=agent.enforced,
                    enabled=control_row is None or control_row.enabled,
                    disabled_reason=control_row.reason if control_row is not None else None,
                    skills=[
                        AgentSkillGrant(skill_name=skill_name, granted_at=grant.granted_at)
                        for grant, skill_name in grants
                    ],
                    last_run_status=last_run.status if last_run is not None else None,
                    last_run_at=last_run.started_at if last_run is not None else None,
                )
            )
        return AgentDetailResponse(agent_id=agent_id, instances=instances)
