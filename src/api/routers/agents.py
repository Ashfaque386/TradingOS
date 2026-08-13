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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents import prompt_registry
from src.agents.control import (
    KNOWN_AGENTS,
    AgentHaltedError,
    UnknownAgentError,
    set_agent_enabled,
)
from src.agents.graph import build_graph
from src.agents.llm_router import fetch_langsmith_trace_url, pop_last_langsmith_run_id
from src.agents.nodes.backtesting import DEFAULT_BACKTEST_LOOKBACK_DAYS, DEFAULT_INITIAL_CAPITAL
from src.agents.prompt_registry import PromptNotFoundError
from src.agents.state import StrategyOptionLeg, TradingOSGraphState
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
from src.models.agent import AgentControlState, AgentLog, AgentRun
from src.models.strategy import BacktestResult, Strategy, StrategyVersion
from src.models.user import User
from src.observability.metrics import AGENT_RUN_DURATION_SECONDS

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


def _summarize_node_output(node_name: str, output: dict[str, Any]) -> str:
    """A short, honest summary of what a node actually returned -- built from the real
    Pydantic fields in `output`, never a canned string."""
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
        strategy = Strategy(
            account_id=tracking.account_id,
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

    if node_name == "options_strategy_agent" and "strategy_logic" in output:
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
            sharpe_ratio=metrics.sharpe_ratio,
            sortino_ratio=metrics.sortino_ratio,
            calmar_ratio=metrics.calmar_ratio,
            max_drawdown=metrics.max_drawdown,
            cagr=metrics.cagr,
            win_rate=metrics.win_rate,
            profit_factor=metrics.profit_factor,
            expectancy=metrics.expectancy,
            total_trades=metrics.total_trades,
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


def _execute_graph_run(*, thread_id: str, root_run_id: uuid.UUID) -> None:
    """Runs in a FastAPI BackgroundTasks worker thread (dispatched after the trigger endpoint
    already returned). Synchronous end-to-end because every graph node (src/agents/nodes/*.py)
    and `graph.stream()` itself are synchronous."""
    redis_client = get_redis_client()
    graph = build_graph()
    state = TradingOSGraphState(thread_id=thread_id, account_capital=_fetch_account_capital())
    checkpoint_wall = datetime.now(UTC)
    tracking = _StrategyTracking()

    try:
        for step in graph.stream(state):
            for node_name, output in step.items():
                now_wall = datetime.now(UTC)
                AGENT_RUN_DURATION_SECONDS.labels(agent_name=node_name).observe(
                    (now_wall - checkpoint_wall).total_seconds()
                )
                summary = _summarize_node_output(node_name, output)

                jsonable_output = {k: _jsonable(v) for k, v in output.items()}
                # REL-009 E9.2 (NFR-05): the node just returned, so pop whatever run id complete()
                # last set during its execution (None if the node made no LLM call, or tracing
                # isn't configured) and resolve it to a real LangSmith URL before persisting.
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
            if root is not None:
                root.status = "Completed"
                root.ended_at = datetime.now(UTC)
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


# --- Orchestrator HITL (REL-010 E10.8d, API-020..024) -----------------------------------------


class RetryResponse(BaseModel):
    run_id: uuid.UUID
    retried_from_run_id: uuid.UUID
    thread_id: str
    status: str


@router.post("/runs/{run_id}/retry", response_model=RetryResponse, status_code=202)
def retry_run(run_id: uuid.UUID, _user: User = Depends(_can_manage_hitl)) -> RetryResponse:
    """API-021. Valid only for a run that genuinely ended `"Failed"` -- dispatches a fresh
    end-to-end graph run via the same detached-thread machinery as `/research/trigger`, with
    `retried_from_run_id` linking it back to the run a human asked to retry."""
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
