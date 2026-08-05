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

import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from src.api.deps import require_role
from src.core.audit import write_audit_entry
from src.core.config import get_settings
from src.core.db import get_session
from src.core.security import ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER, ROLE_SYSTEM_ADMINISTRATOR
from src.data.datalake.query import DataLake
from src.engine.optimization.monte_carlo import run_monte_carlo_simulation
from src.engine.optimization.monte_carlo_persistence import persist_monte_carlo_p95_max_drawdown
from src.engine.sandbox.backtest_runner import (
    EquityPoint,
    RealBacktestOutcome,
    run_real_backtest,
    write_equity_curve_parquet,
)
from src.models.strategy import BacktestResult, Strategy, StrategyVersion
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

DEFAULT_BACKTEST_LOOKBACK_DAYS = 365
DEFAULT_INITIAL_CAPITAL = 100_000.0


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


class StrategyVersionSummary(BaseModel):
    id: uuid.UUID
    version_no: int
    validation_status: str
    validator_feedback: str | None


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


class StrategyDetail(StrategySummary):
    versions: list[StrategyVersionSummary]
    backtests: list[BacktestSummary]


def _to_summary(strategy: Strategy) -> StrategySummary:
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
    )


@router.get("", response_model=list[StrategySummary])
def list_strategies() -> list[StrategySummary]:
    with get_session() as session:
        strategies = session.scalars(select(Strategy).order_by(Strategy.created_at.desc()))
        return [_to_summary(s) for s in strategies]


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

        return StrategyDetail(
            **_to_summary(strategy).model_dump(),
            versions=[
                StrategyVersionSummary(
                    id=v.id,
                    version_no=v.version_no,
                    validation_status=v.validation_status,
                    validator_feedback=v.validator_feedback,
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


@router.get("/backtests/{backtest_id}/equity-curve", response_model=list[EquityCurvePoint])
def get_equity_curve(backtest_id: uuid.UUID) -> list[EquityCurvePoint]:
    import polars as pl

    with get_session() as session:
        result = session.get(BacktestResult, backtest_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Backtest not found")
        if not result.equity_curve_path:
            return []
        df = pl.read_parquet(result.equity_curve_path)
        return [
            EquityCurvePoint(date=str(row["date"]), equity=float(row["equity"]))
            for row in df.iter_rows(named=True)
        ]


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
