"""Strategy Deployment & Backtest Review endpoints (Phase 4 Epic E4.3), backing
Phase_7_Frontend_Architecture.md §2.3:

  - GET  /strategies                              -- Kanban board data (all strategies; the
    frontend groups by `status` into Ideation/Coding/Backtesting/PaperTrading/Live columns).
  - GET  /strategies/{id}                         -- one strategy + its version history +
    backtest history.
  - GET  /strategies/{id}/versions/{version_no}   -- one version's full source, for client-side
    diffing against another version.
  - POST /strategies/{id}/backtest                -- runs a REAL backtest (real historical
    prices, real vectorbt execution inside the sandbox) against the strategy's current version;
    returns immediately with a job id to poll, since a cold run takes ~60-90s (vectorbt's numba
    JIT compiles fresh in every sandboxed subprocess).
  - GET  /strategies/backtests/{job_id}/status    -- poll a backtest job.
  - GET  /strategies/backtests/{backtest_id}/equity-curve -- the persisted equity curve.
  - GET  /strategies/backtests/{backtest_id}/trades       -- the real per-trade ledger (REL-022).
  - GET  /strategies/backtests/{backtest_id}/walk-forward -- real Walk-Forward Optimization
    window summaries (REL-024), when there was enough real history for at least one rolling
    window.
  - POST /strategies/{id}/promote                 -- the human-approval action: Kanban
    drag-to-column maps directly to this, moving `status` to Backtesting/PaperTrading/Live/
    Deprecated (never back to the agent-only Ideation/Coding states).

Before this router existed, nothing in the codebase ever wrote a Strategy/StrategyVersion/
BacktestResult row in production -- src/api/routers/agents.py's `_persist_strategy_progress`
(added alongside this router) is what populates them from the real LangGraph pipeline; this
router is the read/action surface on top of that real data.

`/promote` requires SystemAdministrator or PortfolioManager, per Phase_12_Security_Design.md
§2.2's "Approve Paper -> Live strategy deployment (Rule 3)" permission row -- applied uniformly
to every status transition this endpoint handles (not just Paper->Live) since it's the one real
human-approval action in this router and the strictest applicable gate. Everything else here is
read-only and stays open, matching every other Phase 4 router's convention.

REL-011 E10.11.0: `/backtest` was found to have NO auth dependency at all during frontend-
completeness research -- any caller, including an unauthenticated one, could launch a real
vectorbt backtest run. Gated to SystemAdministrator/PortfolioManager/RiskManager (the same set
as agents.py's Orchestrator HITL endpoints), a real fix, not a pre-existing documented gap.
"""

import csv
import io
import json
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Literal

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select

from src.api.deps import get_current_user, require_role
from src.api.routers.agents import run_suggestion_regeneration
from src.core.audit import write_audit_entry
from src.core.config import get_settings
from src.core.db import get_session
from src.core.security import ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER, ROLE_SYSTEM_ADMINISTRATOR
from src.data.datalake.query import DataLake
from src.engine.optimization.monte_carlo import run_monte_carlo_simulation
from src.engine.optimization.monte_carlo_persistence import persist_monte_carlo_p95_max_drawdown
from src.engine.optimization.walk_forward_adapter import run_walk_forward_from_real_backtest
from src.engine.paper_trading.paper_account import get_paper_account
from src.engine.sandbox.backtest_runner import (
    EquityPoint,
    RealBacktestOutcome,
    run_real_backtest,
    write_equity_curve_parquet,
)
from src.models.strategy import BacktestResult, Strategy, StrategySuggestion, StrategyVersion
from src.models.user import User

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])

_can_promote = require_role(ROLE_SYSTEM_ADMINISTRATOR, ROLE_PORTFOLIO_MANAGER, audit_denials=True)
# REL-011 E10.11.0: found with NO auth dependency at all -- any caller, including
# unauthenticated ones, could launch a real vectorbt backtest run. Gated to the same SA/PM/RM
# set as src/api/routers/agents.py's Orchestrator HITL endpoints (_can_manage_hitl), since
# triggering a real backtest is an equivalent-weight operational action.
_can_trigger_backtest = require_role(
    ROLE_SYSTEM_ADMINISTRATOR, ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER, audit_denials=True
)
# REL-048: reviewing a suggestion re-enters the real agent pipeline (real LLM calls, a real
# sandboxed backtest) -- the same weight/role set as _can_trigger_backtest. Submitting a
# suggestion itself is cheap (one DB row) and open to any authenticated user, matching this
# feature's own "anyone can propose, SA/PM/RM decide whether it's worth an AI-triggered rerun"
# shape.
_can_review_suggestion = require_role(
    ROLE_SYSTEM_ADMINISTRATOR, ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER, audit_denials=True
)

DEFAULT_BACKTEST_LOOKBACK_DAYS = 365
DEFAULT_INITIAL_CAPITAL = 100_000.0
# Mirrors src/api/routers/agents.py's own _DEFAULT_MAX_DRAWDOWN_LIMIT (same 15% figure, same
# kill_switch.py DEFAULT_KILL_SWITCH_THRESHOLD precedent) -- no Risk Manager Agent exists yet to
# set a real per-strategy limit at manual-creation time either.
_DEFAULT_MAX_DRAWDOWN_LIMIT = 15.00


# --- List / detail ----------------------------------------------------------------------------


class StrategySummary(BaseModel):
    id: uuid.UUID
    name: str
    hypothesis: str | None
    asset_class: str
    style: str
    status: str
    universe: list[str] | None
    current_version_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime | None
    # REL-040: real count of BacktestResult rows across every version of this strategy -- lets
    # the frontend show which strategies actually have backtest history worth picking, instead
    # of the user discovering "this one has none" only after selecting it and seeing an empty
    # detail view.
    backtest_count: int = 0
    # REL-044: real, previously-unserialized columns. max_drawdown_limit has always existed
    # (Strategy's own per-strategy risk parameter, set at creation); the rest are the Strategy
    # Generator Agent's StrategyLogic fields (src/agents/state.py) beyond hypothesis -- computed
    # by the LLM on every run since Phase 2 but only ever partially copied onto this row until
    # this release (src/api/routers/agents.py::_persist_strategy_progress). `None` for a row
    # created before this migration, honestly, not backfilled. research_context/market_context
    # are the CEO/Market Analyst Agents' own real ResearchDirective/MarketContext that led to
    # this strategy being proposed -- same honest-null convention.
    max_drawdown_limit: float | None = None
    entry_conditions: str | None = None
    exit_conditions: str | None = None
    stop_loss: str | None = None
    take_profit: str | None = None
    position_sizing: str | None = None
    confidence_score: float | None = None
    research_context: dict[str, object] | None = None
    market_context: dict[str, object] | None = None
    # REL-044: the current version's own validation_status, so the Kanban card can show a real
    # status indicator without a second round trip -- StrategySummary previously only carried
    # current_version_id (a bare UUID), never what that version's own state actually is.
    current_version_validation_status: str | None = None


class StrategyVersionSummary(BaseModel):
    id: uuid.UUID
    version_no: int
    validation_status: str
    validator_feedback: str | None
    # REL-044: real columns on StrategyVersion (option_legs/option_expiry real since REL-035,
    # option_rationale new this release) -- persisted but never serialized by this endpoint
    # until now. All None for an Equity strategy, or an F&O one whose options grounding
    # degraded (see src/agents/nodes/options_strategy_agent.py's own module docstring).
    option_legs: list[dict[str, float | str | int]] | None = None
    option_expiry: date | None = None
    option_rationale: str | None = None


class BacktestSummary(BaseModel):
    id: uuid.UUID
    strategy_version_id: uuid.UUID
    date_from: date
    date_to: date
    sharpe_ratio: float | None
    sortino_ratio: float | None
    calmar_ratio: float | None
    max_drawdown: float | None
    cagr: float | None
    win_rate: float | None
    profit_factor: float | None
    expectancy: float | None
    total_trades: int | None
    has_equity_curve: bool
    # REL-017 E17.4 (DB-007): real column, real since Phase 3, exposed here since that release.
    # UPDATE 2026-08-05 (REL-023 E23.1): _run_backtest_job now calls run_monte_carlo_simulation()
    # with real per-trade returns (REL-022's trades ledger) and persists the result via
    # persist_monte_carlo_p95_max_drawdown() -- the gap this comment used to describe ("nothing
    # in this pipeline ever calls" it) is closed. Still `None` for backtests created before this
    # release (not backfilled) or ones with fewer than 2 usable returns either way.
    monte_carlo_p95_max_drawdown: float | None
    created_at: datetime
    # REL-040: real columns on BacktestResult (src/models/strategy.py, REL-005) written by the
    # real LangGraph Evaluator/Optimization/RiskManager/Deployment agent nodes
    # (src/api/routers/agents.py::_persist_strategy_progress) -- computed and persisted for
    # every real graph-driven backtest since REL-005, but never serialized by this endpoint
    # until now. `None` for a backtest triggered directly via POST /{id}/backtest (this router's
    # own _run_backtest_job never sets these -- it's a standalone re-run, not a full graph
    # pass) or for one created before REL-005, not fabricated either way.
    evaluation_verdict: str | None = None
    evaluation_failure_reasons: list[str] | None = None
    optimization_best_params: dict[str, float] | None = None
    optimization_robustness_score: float | None = None
    risk_assessment_passed: bool | None = None
    risk_assessment_notes: str | None = None
    deployment_recommendation: str | None = None
    deployment_rationale: str | None = None


class StrategyDetail(StrategySummary):
    versions: list[StrategyVersionSummary]
    backtests: list[BacktestSummary]


def _to_summary(
    strategy: Strategy,
    *,
    backtest_count: int = 0,
    current_version_validation_status: str | None = None,
) -> StrategySummary:
    return StrategySummary(
        id=strategy.id,
        name=strategy.name,
        hypothesis=strategy.hypothesis,
        asset_class=strategy.asset_class,
        style=strategy.style,
        status=strategy.status,
        universe=strategy.universe,
        current_version_id=strategy.current_version_id,
        created_at=strategy.created_at,
        updated_at=strategy.updated_at,
        backtest_count=backtest_count,
        max_drawdown_limit=strategy.max_drawdown_limit,
        entry_conditions=strategy.entry_conditions,
        exit_conditions=strategy.exit_conditions,
        stop_loss=strategy.stop_loss,
        take_profit=strategy.take_profit,
        position_sizing=strategy.position_sizing,
        confidence_score=strategy.confidence_score,
        research_context=strategy.research_context,
        market_context=strategy.market_context,
        current_version_validation_status=current_version_validation_status,
    )


def _to_backtest_summary(result: BacktestResult) -> BacktestSummary:
    return BacktestSummary(
        id=result.id,
        strategy_version_id=result.strategy_version_id,
        date_from=result.date_from,
        date_to=result.date_to,
        sharpe_ratio=result.sharpe_ratio,
        sortino_ratio=result.sortino_ratio,
        calmar_ratio=result.calmar_ratio,
        max_drawdown=result.max_drawdown,
        cagr=result.cagr,
        win_rate=result.win_rate,
        profit_factor=result.profit_factor,
        expectancy=result.expectancy,
        total_trades=result.total_trades,
        has_equity_curve=bool(result.equity_curve_path),
        monte_carlo_p95_max_drawdown=result.monte_carlo_p95_max_drawdown,
        created_at=result.created_at,
        evaluation_verdict=result.evaluation_verdict,
        evaluation_failure_reasons=result.evaluation_failure_reasons,
        optimization_best_params=result.optimization_best_params,
        optimization_robustness_score=result.optimization_robustness_score,
        risk_assessment_passed=result.risk_assessment_passed,
        risk_assessment_notes=result.risk_assessment_notes,
        deployment_recommendation=result.deployment_recommendation,
        deployment_rationale=result.deployment_rationale,
    )


class CreateStrategyRequest(BaseModel):
    name: str
    hypothesis: str | None = None
    asset_class: Literal["Equity", "F&O"]
    style: Literal["Intraday", "Swing"]
    universe: list[str] | None = None
    max_drawdown_limit: float = float(_DEFAULT_MAX_DRAWDOWN_LIMIT)


@router.post("", response_model=StrategySummary, status_code=201)
def create_strategy(
    body: CreateStrategyRequest, _user: User = Depends(_can_trigger_backtest)
) -> StrategySummary:
    """API-041. Registers a strategy hypothesis manually, starting in "Ideation" (Strategy's own
    default) -- the same lifecycle every agent-generated strategy enters through
    src/api/routers/agents.py::_persist_strategy_progress, just without a LangGraph run behind
    it. `account_id` reuses the same lazy-seeded Paper account every other strategy/backtest
    write in this codebase resolves against (get_paper_account) -- strategies aren't
    broker-scoped, so there is no real "which account" question to ask the caller. Gated the
    same as triggering a backtest (SA/PM/RM): registering a hypothesis that will go on to consume
    real backtest/LLM budget is an equivalent-weight operational action, not a plain read."""
    with get_session() as session:
        account = get_paper_account(session)
        strategy = Strategy(
            account_id=account.id,
            name=body.name,
            hypothesis=body.hypothesis,
            asset_class=body.asset_class,
            style=body.style,
            universe=body.universe,
            max_drawdown_limit=body.max_drawdown_limit,
            created_by_agent="Human",
        )
        session.add(strategy)
        session.commit()
        session.refresh(strategy)
        return _to_summary(strategy)


class UpdateStrategyRequest(BaseModel):
    name: str | None = None
    hypothesis: str | None = None
    universe: list[str] | None = None
    max_drawdown_limit: float | None = None


@router.patch("/{strategy_id}", response_model=StrategySummary)
def update_strategy(
    strategy_id: uuid.UUID,
    body: UpdateStrategyRequest,
    _user: User = Depends(_can_trigger_backtest),
) -> StrategySummary:
    """API-042. Metadata-only update -- asset_class/style/status are deliberately not editable
    here: asset_class/style are fixed at creation (changing them mid-lifecycle would invalidate
    any existing StrategyVersion's code), and status only ever moves through `/promote`'s real
    lifecycle gate below, never a free-form PATCH. Same role gate as `create_strategy` above."""
    with get_session() as session:
        strategy = session.get(Strategy, strategy_id)
        if strategy is None:
            raise HTTPException(status_code=404, detail="Strategy not found")
        for field, value in body.model_dump(exclude_unset=True).items():
            setattr(strategy, field, value)
        session.commit()
        session.refresh(strategy)
        return _to_summary(strategy)


@router.get("", response_model=list[StrategySummary])
def list_strategies() -> list[StrategySummary]:
    with get_session() as session:
        strategies = list(session.scalars(select(Strategy).order_by(Strategy.created_at.desc())))
        # REL-040: one grouped query for every strategy's real backtest_count, rather than an
        # N+1 count-per-strategy -- joins through StrategyVersion since BacktestResult only has
        # a strategy_version_id, not a direct strategy_id.
        counts: dict[uuid.UUID, int] = dict(
            session.execute(
                select(StrategyVersion.strategy_id, func.count(BacktestResult.id))
                .join(BacktestResult, BacktestResult.strategy_version_id == StrategyVersion.id)
                .group_by(StrategyVersion.strategy_id)
            ).all()  # type: ignore[arg-type]
        )
        # REL-044: current version's own validation_status, joined via Strategy.current_version_id
        # rather than StrategyVersion.strategy_id -- a strategy can have several versions (each
        # retry/regeneration creates one), only the current one's status belongs on the Kanban card.
        version_statuses: dict[uuid.UUID, str] = dict(
            session.execute(
                select(Strategy.id, StrategyVersion.validation_status).join(
                    StrategyVersion, StrategyVersion.id == Strategy.current_version_id
                )
            ).all()  # type: ignore[arg-type]
        )
        return [
            _to_summary(
                s,
                backtest_count=counts.get(s.id, 0),
                current_version_validation_status=version_statuses.get(s.id),
            )
            for s in strategies
        ]


@router.get("/{strategy_id}", response_model=StrategyDetail)
def get_strategy(strategy_id: uuid.UUID) -> StrategyDetail:
    with get_session() as session:
        strategy = session.get(Strategy, strategy_id)
        if strategy is None:
            raise HTTPException(status_code=404, detail="Strategy not found")

        versions = list(
            session.scalars(
                select(StrategyVersion)
                .where(StrategyVersion.strategy_id == strategy_id)
                .order_by(StrategyVersion.version_no)
            )
        )
        version_ids = [v.id for v in versions]
        backtests = (
            list(
                session.scalars(
                    select(BacktestResult)
                    .where(BacktestResult.strategy_version_id.in_(version_ids))
                    .order_by(BacktestResult.created_at.desc())
                )
            )
            if version_ids
            else []
        )

        current_version = next((v for v in versions if v.id == strategy.current_version_id), None)
        return StrategyDetail(
            **_to_summary(
                strategy,
                backtest_count=len(backtests),
                current_version_validation_status=(
                    current_version.validation_status if current_version else None
                ),
            ).model_dump(),
            versions=[
                StrategyVersionSummary(
                    id=v.id,
                    version_no=v.version_no,
                    validation_status=v.validation_status,
                    validator_feedback=v.validator_feedback,
                    option_legs=v.option_legs,
                    option_expiry=v.option_expiry,
                    option_rationale=v.option_rationale,
                )
                for v in versions
            ],
            backtests=[_to_backtest_summary(b) for b in backtests],
        )


class VersionCode(BaseModel):
    version_no: int
    python_code: str


@router.get("/{strategy_id}/versions/{version_no}", response_model=VersionCode)
def get_version_code(strategy_id: uuid.UUID, version_no: int) -> VersionCode:
    with get_session() as session:
        version = session.scalars(
            select(StrategyVersion).where(
                StrategyVersion.strategy_id == strategy_id, StrategyVersion.version_no == version_no
            )
        ).first()
        if version is None:
            raise HTTPException(status_code=404, detail="Version not found")
        return VersionCode(version_no=version.version_no, python_code=version.python_code)


# --- Real backtest trigger (async job, in-memory status -- see module docstring) --------------


@dataclass
class _BacktestJob:
    status: Literal["Running", "Completed", "Failed"]
    error: str | None = None
    backtest_result_id: uuid.UUID | None = None


_backtest_jobs: dict[str, _BacktestJob] = {}
_backtest_jobs_lock = threading.Lock()


class BacktestTriggerResponse(BaseModel):
    job_id: str
    status: str


class BacktestJobStatusResponse(BaseModel):
    job_id: str
    status: str
    error: str | None
    backtest_result_id: uuid.UUID | None


def _equity_curve_returns(equity_curve: list[EquityPoint]) -> list[float]:
    """REL-023: the same daily-return derivation src/agents/nodes/optimization.py's own
    LangGraph path already uses for its Monte Carlo input -- duplicated rather than imported
    from that agent-node module (a different layer of this codebase) since it's 3 lines with no
    real shared state to couple on."""
    values = [point.equity for point in equity_curve]
    return [
        (curr - prev) / prev for prev, curr in zip(values, values[1:], strict=False) if prev != 0
    ]


def _run_backtest_job(
    *,
    job_id: str,
    strategy_id: uuid.UUID,
    version: StrategyVersionSummary,
    universe: list[str],
    date_from: date,
    date_to: date,
) -> None:
    outcome: RealBacktestOutcome = run_real_backtest(
        # python_code isn't on StrategyVersionSummary; re-fetched by id below to keep this
        # thread's DB access self-contained rather than passing a detached ORM object across
        # threads.
        _fetch_code(version.id),
        universe=universe,
        date_from=date_from,
        date_to=date_to,
        config={"init_cash": DEFAULT_INITIAL_CAPITAL},
    )

    if not outcome.passed:
        with _backtest_jobs_lock:
            _backtest_jobs[job_id] = _BacktestJob(status="Failed", error=outcome.error)
        return

    with get_session() as session:
        result = BacktestResult(
            strategy_version_id=version.id,
            date_from=date_from,
            date_to=date_to,
            initial_capital=DEFAULT_INITIAL_CAPITAL,
            sharpe_ratio=outcome.metrics.get("sharpe_ratio"),
            sortino_ratio=outcome.metrics.get("sortino_ratio"),
            calmar_ratio=outcome.metrics.get("calmar_ratio"),
            max_drawdown=outcome.metrics.get("max_drawdown"),
            cagr=outcome.metrics.get("cagr"),
            win_rate=outcome.metrics.get("win_rate"),
            profit_factor=outcome.metrics.get("profit_factor"),
            expectancy=outcome.metrics.get("expectancy"),
            total_trades=outcome.metrics.get("total_trades"),
            # REL-022: whatever _extract_trades parsed -- an empty list either way for a
            # pre-v3-contract strategy or a real v3 strategy with zero closed trades in the
            # window (backtest_runner.py can't distinguish the two, same limitation
            # _extract_equity_curve already has for a missing-vs-malformed equity curve).
            trades=[asdict(t) for t in outcome.trades],
            # REL-024: real Walk-Forward window summaries, when there was enough real
            # entries_exits/close_curve history for at least one rolling window -- None (not an
            # empty list) otherwise, matching every other honestly-nothing-here JSONB column on
            # this row.
            walk_forward_results=[
                asdict(w)
                for w in run_walk_forward_from_real_backtest(
                    [(p.date, p.close) for p in outcome.close_curve],
                    [(p.date, p.entry, p.exit) for p in outcome.entries_exits],
                )
            ]
            or None,
        )
        session.add(result)
        session.flush()
        equity_path = write_equity_curve_parquet(outcome, backtest_result_id=str(result.id))
        if equity_path is not None:
            result.equity_curve_path = str(equity_path)
        session.commit()
        result_id = result.id

        # REL-023 E23.1: real per-trade returns when a real trade ledger exists (REL-022),
        # falling back to the coarser daily-equity-curve-derived returns
        # optimization_node's own LangGraph path already uses when it doesn't (pre-v3-contract
        # strategies, or zero real trades in the window) -- same >=2-usable-returns gate that
        # node already applies, for consistency. Left honestly unset (not a fabricated 0.0) when
        # there's not enough data either way, matching this row's own pre-REL-023 comment.
        trade_returns = [t.return_pct for t in outcome.trades] or _equity_curve_returns(
            outcome.equity_curve
        )
        if len(trade_returns) >= 2:
            mc_result = run_monte_carlo_simulation(trade_returns)
            persist_monte_carlo_p95_max_drawdown(
                session, result_id, mc_result.percentile_95_max_drawdown
            )

    with _backtest_jobs_lock:
        _backtest_jobs[job_id] = _BacktestJob(status="Completed", backtest_result_id=result_id)


def _fetch_code(version_id: uuid.UUID) -> str:
    with get_session() as session:
        version = session.get(StrategyVersion, version_id)
        if version is None:
            raise ValueError(f"StrategyVersion {version_id} vanished before the backtest job ran")
        return version.python_code


@router.post("/{strategy_id}/backtest", response_model=BacktestTriggerResponse, status_code=202)
def trigger_backtest(
    strategy_id: uuid.UUID, _user: User = Depends(_can_trigger_backtest)
) -> BacktestTriggerResponse:
    with get_session() as session:
        strategy = session.get(Strategy, strategy_id)
        if strategy is None:
            raise HTTPException(status_code=404, detail="Strategy not found")
        if strategy.current_version_id is None:
            raise HTTPException(status_code=409, detail="Strategy has no code version yet")
        if not strategy.universe:
            raise HTTPException(
                status_code=409,
                detail="Strategy has no universe recorded -- can't load historical data for it",
            )
        version = session.get(StrategyVersion, strategy.current_version_id)
        if version is None:
            raise HTTPException(status_code=409, detail="Current version record is missing")
        version_summary = StrategyVersionSummary(
            id=version.id,
            version_no=version.version_no,
            validation_status=version.validation_status,
            validator_feedback=version.validator_feedback,
        )
        universe = list(strategy.universe)

    # A trailing window ending at the *data lake's* latest ingested bar for this symbol, not
    # wall-clock "now": this system does a one-time historical backfill (Phase 1), it doesn't
    # continuously ingest daily bars, so "the last 365 days from today" would almost always miss
    # every real symbol's actual coverage and fail with a false "no historical data" error.
    lake = DataLake(get_settings().data_lake_root / "ohlcv_daily")
    date_to = lake.latest_date(universe[0])
    if date_to is None:
        raise HTTPException(
            status_code=409,
            detail=f"No historical data ingested for {universe[0]} -- nothing to backtest against",
        )
    date_from = date_to.fromordinal(date_to.toordinal() - DEFAULT_BACKTEST_LOOKBACK_DAYS)

    job_id = str(uuid.uuid4())
    with _backtest_jobs_lock:
        _backtest_jobs[job_id] = _BacktestJob(status="Running")

    threading.Thread(
        target=_run_backtest_job,
        kwargs={
            "job_id": job_id,
            "strategy_id": strategy_id,
            "version": version_summary,
            "universe": universe,
            "date_from": date_from,
            "date_to": date_to,
        },
        daemon=True,
    ).start()

    return BacktestTriggerResponse(job_id=job_id, status="Running")


@router.get("/backtests/jobs/{job_id}/status", response_model=BacktestJobStatusResponse)
def get_backtest_job_status(job_id: str) -> BacktestJobStatusResponse:
    with _backtest_jobs_lock:
        job = _backtest_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown backtest job (or the app restarted)")
    return BacktestJobStatusResponse(
        job_id=job_id, status=job.status, error=job.error, backtest_result_id=job.backtest_result_id
    )


class EquityCurvePoint(BaseModel):
    date: str
    equity: float


def _read_equity_curve(result: BacktestResult) -> list[EquityCurvePoint]:
    """REL-040: extracted from get_equity_curve below so the new /compare endpoint can reuse the
    identical real parquet-read logic per row rather than duplicating it."""
    import polars as pl

    if not result.equity_curve_path:
        return []
    df = pl.read_parquet(result.equity_curve_path)
    return [
        EquityCurvePoint(date=str(row["date"]), equity=float(row["equity"]))
        for row in df.iter_rows(named=True)
    ]


@router.get("/backtests/{backtest_id}/equity-curve", response_model=list[EquityCurvePoint])
def get_equity_curve(backtest_id: uuid.UUID) -> list[EquityCurvePoint]:
    with get_session() as session:
        result = session.get(BacktestResult, backtest_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Backtest not found")
        return _read_equity_curve(result)


class TradeSummary(BaseModel):
    entry_date: str
    exit_date: str
    side: str
    size: float
    entry_price: float
    exit_price: float
    pnl: float
    return_pct: float


@router.get("/backtests/{backtest_id}/trades", response_model=list[TradeSummary])
def get_trades(backtest_id: uuid.UUID) -> list[TradeSummary]:
    """REL-023 E23.2. Mirrors get_equity_curve's shape, but `trades` lives directly on the
    `BacktestResult` row as JSONB (REL-022) rather than a separate parquet file -- no extra I/O
    needed. Empty list (not a 404) for a real backtest with zero closed trades or one that
    predates the v3 sandbox contract -- same "honestly nothing here" convention as the equity
    curve endpoint above."""
    with get_session() as session:
        result = session.get(BacktestResult, backtest_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Backtest not found")
        if not result.trades:
            return []
        return [TradeSummary(**trade) for trade in result.trades]


class WalkForwardWindowResponse(BaseModel):
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    train_expectancy: float | None
    test_expectancy: float | None
    test_sharpe_ratio: float | None
    test_total_trades: int | None
    out_of_sample_passed: bool


@router.get("/backtests/{backtest_id}/walk-forward", response_model=list[WalkForwardWindowResponse])
def get_walk_forward(backtest_id: uuid.UUID) -> list[WalkForwardWindowResponse]:
    """REL-024 E24.3. Mirrors get_trades's shape -- `walk_forward_results` lives directly on the
    `BacktestResult` row as JSONB, no extra I/O. Empty list (not a 404) for a real backtest with
    too little real entries/exits or price history for even one rolling window, or one that
    predates the v3 sandbox contract / this release -- same "honestly nothing here" convention as
    the trades and equity curve endpoints above."""
    with get_session() as session:
        result = session.get(BacktestResult, backtest_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Backtest not found")
        if not result.walk_forward_results:
            return []
        return [WalkForwardWindowResponse(**window) for window in result.walk_forward_results]


# --- Cross-strategy views (REL-040) ------------------------------------------------------------


class BacktestWithStrategy(BacktestSummary):
    strategy_id: uuid.UUID
    strategy_name: str


class BacktestCompareRow(BacktestWithStrategy):
    equity_curve: list[EquityCurvePoint]


@router.get("/backtests/latest", response_model=list[BacktestWithStrategy])
def list_latest_backtests() -> list[BacktestWithStrategy]:
    """REL-040: real, server-side "most recent backtest per strategy" -- replaces the frontend's
    own N+1 client-side fetch (one GET /{id} per strategy) that existed only to build this exact
    cross-strategy view. A strategy with no version or no backtest at all is simply absent from
    the result, the same honest-omission convention every other endpoint in this router uses."""
    with get_session() as session:
        latest_per_strategy = (
            select(
                StrategyVersion.strategy_id.label("strategy_id"),
                func.max(BacktestResult.created_at).label("max_created_at"),
            )
            .join(BacktestResult, BacktestResult.strategy_version_id == StrategyVersion.id)
            .group_by(StrategyVersion.strategy_id)
            .subquery()
        )
        rows = session.execute(
            select(BacktestResult, Strategy.id, Strategy.name)
            .join(StrategyVersion, StrategyVersion.id == BacktestResult.strategy_version_id)
            .join(Strategy, Strategy.id == StrategyVersion.strategy_id)
            .join(
                latest_per_strategy,
                (StrategyVersion.strategy_id == latest_per_strategy.c.strategy_id)
                & (BacktestResult.created_at == latest_per_strategy.c.max_created_at),
            )
            .order_by(Strategy.name)
        ).all()
        return [
            BacktestWithStrategy(
                **_to_backtest_summary(result).model_dump(),
                strategy_id=strategy_id,
                strategy_name=strategy_name,
            )
            for result, strategy_id, strategy_name in rows
        ]


@router.get("/backtests/compare", response_model=list[BacktestCompareRow])
def compare_backtests(
    ids: str = Query(..., description="Comma-separated backtest UUIDs, max 6"),
) -> list[BacktestCompareRow]:
    """REL-040: arbitrary multi-run comparison (not just "latest per strategy") -- a bad or
    vanished id is silently omitted from the response, not a failed batch, the same per-entry
    graceful-degradation convention src/api/routers/portfolio.py's by-broker endpoints already
    established. Includes each row's real equity curve so the frontend can overlay them from one
    round trip instead of N follow-up requests."""
    raw_ids = [i.strip() for i in ids.split(",") if i.strip()]
    if len(raw_ids) > 6:
        raise HTTPException(
            status_code=422, detail="At most 6 backtest ids may be compared at once"
        )
    try:
        parsed_ids = [uuid.UUID(i) for i in raw_ids]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid backtest id: {exc}") from exc

    rows: list[BacktestCompareRow] = []
    with get_session() as session:
        for backtest_id in parsed_ids:
            result = session.get(BacktestResult, backtest_id)
            if result is None:
                continue
            version = session.get(StrategyVersion, result.strategy_version_id)
            if version is None:
                continue
            strategy = session.get(Strategy, version.strategy_id)
            if strategy is None:
                continue
            rows.append(
                BacktestCompareRow(
                    **_to_backtest_summary(result).model_dump(),
                    strategy_id=strategy.id,
                    strategy_name=strategy.name,
                    equity_curve=_read_equity_curve(result),
                )
            )
    return rows


class MonteCarloHistogramResponse(BaseModel):
    bucket_edges: list[float]
    bucket_counts: list[int]
    percentile_95_max_drawdown: float
    historical_max_drawdown: float
    n_simulations: int


@router.get("/backtests/{backtest_id}/monte-carlo", response_model=MonteCarloHistogramResponse)
def get_monte_carlo_histogram(backtest_id: uuid.UUID) -> MonteCarloHistogramResponse:
    """REL-040: recomputes the full Monte Carlo drawdown distribution live from the already-
    persisted real trade ledger (REL-022) -- cheap (milliseconds, pure numpy resampling), no
    schema change, no re-running the sandboxed vectorbt backtest. Only the single percentile_95
    summary is ever persisted (REL-023, BacktestResult.monte_carlo_p95_max_drawdown); the full
    distribution this endpoint returns is always computed fresh and never written back."""
    with get_session() as session:
        result = session.get(BacktestResult, backtest_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Backtest not found")
        trade_returns = [float(t["return_pct"]) for t in (result.trades or [])]

    if len(trade_returns) < 2:
        raise HTTPException(
            status_code=409,
            detail="Not enough real closed trades (need at least 2) to run a Monte Carlo "
            "simulation",
        )

    mc_result = run_monte_carlo_simulation(trade_returns)
    counts, edges = np.histogram(mc_result.simulated_max_drawdowns, bins=40)
    return MonteCarloHistogramResponse(
        bucket_edges=[float(e) for e in edges],
        bucket_counts=[int(c) for c in counts],
        percentile_95_max_drawdown=float(mc_result.percentile_95_max_drawdown),
        historical_max_drawdown=float(mc_result.historical_max_drawdown),
        n_simulations=mc_result.n_simulations,
    )


_TRADE_EXPORT_FIELDNAMES = [
    "entry_date",
    "exit_date",
    "side",
    "size",
    "entry_price",
    "exit_price",
    "pnl",
    "return_pct",
]


@router.get("/backtests/{backtest_id}/export")
def export_backtest_report(
    backtest_id: uuid.UUID,
    export_format: Literal["csv", "ndjson"] = Query(default="csv", alias="format"),
) -> Response:
    """REL-040: mirrors src/api/routers/paper_trading.py::account_statement_export's exact
    CSV/NDJSON pattern -- the real per-trade ledger for this one backtest run."""
    with get_session() as session:
        result = session.get(BacktestResult, backtest_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Backtest not found")
        trades = result.trades or []

    if export_format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=_TRADE_EXPORT_FIELDNAMES)
        writer.writeheader()
        for trade in trades:
            writer.writerow({k: trade.get(k) for k in _TRADE_EXPORT_FIELDNAMES})
        return Response(content=buffer.getvalue(), media_type="text/csv")

    ndjson_body = "\n".join(json.dumps(trade) for trade in trades)
    return Response(content=ndjson_body, media_type="application/x-ndjson")


# --- Promote (human approval) ------------------------------------------------------------------


class PromoteRequest(BaseModel):
    to_status: Literal["Backtesting", "PaperTrading", "Live", "Deprecated"]


@router.post("/{strategy_id}/promote", response_model=StrategySummary)
def promote_strategy(
    strategy_id: uuid.UUID, body: PromoteRequest, _user: User = Depends(_can_promote)
) -> StrategySummary:
    with get_session() as session:
        strategy = session.get(Strategy, strategy_id)
        if strategy is None:
            raise HTTPException(status_code=404, detail="Strategy not found")
        if strategy.status == "Ideation":
            # Nothing to promote yet -- Coding onward all have at least one code version, but
            # Ideation is pre-code, so there's nothing a human approval action could act on.
            raise HTTPException(
                status_code=409, detail="Strategy has no code yet -- nothing to promote"
            )
        if strategy.current_version_id is None:
            raise HTTPException(status_code=409, detail="Strategy has no code version yet")
        old_status = strategy.status
        strategy.status = body.to_status
        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=_user.email,
            action="STRATEGY_PROMOTED",
            entity_type="Strategy",
            entity_id=strategy.id,
            before_state={"status": old_status},
            after_state={"status": body.to_status},
        )
        session.commit()
        return _to_summary(strategy)


# --- Suggestions (REL-048/049) -----------------------------------------------------------------


class SubmitSuggestionRequest(BaseModel):
    text: str


class StrategySuggestionSummary(BaseModel):
    id: uuid.UUID
    strategy_id: uuid.UUID
    submitted_by_user_id: uuid.UUID
    suggestion_text: str
    status: Literal["Pending", "Reviewing", "Rejected", "Applied"]
    ai_verdict: str | None
    ai_reasoning: str | None
    resulting_version_id: uuid.UUID | None
    created_at: datetime
    reviewed_at: datetime | None


def _to_suggestion_summary(suggestion: StrategySuggestion) -> StrategySuggestionSummary:
    return StrategySuggestionSummary(
        id=suggestion.id,
        strategy_id=suggestion.strategy_id,
        submitted_by_user_id=suggestion.submitted_by_user_id,
        suggestion_text=suggestion.suggestion_text,
        status=suggestion.status,
        ai_verdict=suggestion.ai_verdict,
        ai_reasoning=suggestion.ai_reasoning,
        resulting_version_id=suggestion.resulting_version_id,
        created_at=suggestion.created_at,
        reviewed_at=suggestion.reviewed_at,
    )


@router.post(
    "/{strategy_id}/suggestions", response_model=StrategySuggestionSummary, status_code=201
)
def submit_suggestion(
    strategy_id: uuid.UUID,
    body: SubmitSuggestionRequest,
    user: User = Depends(get_current_user),
) -> StrategySuggestionSummary:
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Suggestion text cannot be empty")
    with get_session() as session:
        strategy = session.get(Strategy, strategy_id)
        if strategy is None:
            raise HTTPException(status_code=404, detail="Strategy not found")
        suggestion = StrategySuggestion(
            strategy_id=strategy_id, submitted_by_user_id=user.id, suggestion_text=text
        )
        session.add(suggestion)
        session.commit()
        session.refresh(suggestion)
        return _to_suggestion_summary(suggestion)


@router.get("/{strategy_id}/suggestions", response_model=list[StrategySuggestionSummary])
def list_suggestions(strategy_id: uuid.UUID) -> list[StrategySuggestionSummary]:
    with get_session() as session:
        rows = session.scalars(
            select(StrategySuggestion)
            .where(StrategySuggestion.strategy_id == strategy_id)
            .order_by(StrategySuggestion.created_at.desc())
        )
        return [_to_suggestion_summary(s) for s in rows]


class SuggestionReviewTriggerResponse(BaseModel):
    job_id: str
    status: str


@dataclass
class _SuggestionJob:
    status: Literal["Running", "Completed"]
    suggestion_id: uuid.UUID


_suggestion_jobs: dict[str, _SuggestionJob] = {}
_suggestion_jobs_lock = threading.Lock()


def _run_suggestion_review_job(*, job_id: str, suggestion_id: uuid.UUID) -> None:
    run_suggestion_regeneration(suggestion_id=suggestion_id)
    with _suggestion_jobs_lock:
        _suggestion_jobs[job_id] = _SuggestionJob(status="Completed", suggestion_id=suggestion_id)


@router.post(
    "/{strategy_id}/suggestions/{suggestion_id}/review",
    response_model=SuggestionReviewTriggerResponse,
    status_code=202,
)
def trigger_suggestion_review(
    strategy_id: uuid.UUID,
    suggestion_id: uuid.UUID,
    _user: User = Depends(_can_review_suggestion),
) -> SuggestionReviewTriggerResponse:
    with get_session() as session:
        suggestion = session.get(StrategySuggestion, suggestion_id)
        if suggestion is None or suggestion.strategy_id != strategy_id:
            raise HTTPException(status_code=404, detail="Suggestion not found")
        if suggestion.status != "Pending":
            raise HTTPException(
                status_code=409, detail=f"Suggestion is already {suggestion.status}"
            )

    job_id = str(uuid.uuid4())
    with _suggestion_jobs_lock:
        _suggestion_jobs[job_id] = _SuggestionJob(status="Running", suggestion_id=suggestion_id)

    threading.Thread(
        target=_run_suggestion_review_job,
        kwargs={"job_id": job_id, "suggestion_id": suggestion_id},
        daemon=True,
    ).start()
    return SuggestionReviewTriggerResponse(job_id=job_id, status="Running")


class SuggestionReviewJobStatusResponse(BaseModel):
    job_id: str
    status: str
    suggestion: StrategySuggestionSummary | None = None


@router.get("/suggestions/jobs/{job_id}/status", response_model=SuggestionReviewJobStatusResponse)
def get_suggestion_review_job_status(job_id: str) -> SuggestionReviewJobStatusResponse:
    with _suggestion_jobs_lock:
        job = _suggestion_jobs.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404, detail="Unknown suggestion review job (or the app restarted)"
        )
    with get_session() as session:
        suggestion = session.get(StrategySuggestion, job.suggestion_id)
        return SuggestionReviewJobStatusResponse(
            job_id=job_id,
            status=job.status,
            suggestion=_to_suggestion_summary(suggestion) if suggestion is not None else None,
        )
