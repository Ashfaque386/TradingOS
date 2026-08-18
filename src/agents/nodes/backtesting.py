"""Backtesting Agent node (AGT-006) — REL-005 Epic E5.1.

Wraps the real, already-tested sandboxed backtest engine (src/engine/sandbox/backtest_runner.py)
as a LangGraph node -- Phase_4_AI_Agent_Design.md §6's "Tools: execute_vectorbt_sim()" is exactly
`run_real_backtest()`, real and tested since REL-003. No LLM call: like `python_validator_node`,
this node is deterministic execution, not judgment.

Persistence of the real `BacktestResult` DB row happens in src/api/routers/agents.py's
`_persist_strategy_progress`, not here -- like every other node in this package, this is a pure
function of `TradingOSGraphState` with no DB session, and (like `strategy_generator_node`/
`python_code_generator_node`) has no reliable way to know the real `strategy_version_id`; only
the orchestration layer tracks that lineage.
"""

from datetime import date, timedelta

from src.agents.state import (
    BacktestMetrics,
    ClosePricePoint,
    EntryExitSignal,
    EquityCurvePoint,
    TradingOSGraphState,
)
from src.core.config import get_settings
from src.data.datalake.freshness import require_fresh
from src.data.datalake.query import DataLake
from src.engine.sandbox.backtest_runner import run_real_backtest

DEFAULT_BACKTEST_LOOKBACK_DAYS = 365
DEFAULT_INITIAL_CAPITAL = 100_000.0


def backtesting_node(state: TradingOSGraphState) -> dict[str, object]:
    if state.python_code is None:
        raise ValueError("backtesting_node requires state.python_code")
    if state.strategy_logic is None or not state.strategy_logic.universe:
        raise ValueError("backtesting_node requires state.strategy_logic.universe")

    universe = state.strategy_logic.universe
    lake = DataLake(get_settings().data_lake_root / "ohlcv_daily")

    # Business Rule 4 (Data Freshness), checked against real wall-clock "today" -- not the
    # backtest window's own end date, which is anchored to the lake's latest ingested bar below
    # and would make a same-date check tautological. This catches a stalled ingestion pipeline
    # even when a valid (if stale) historical window still exists to backtest against.
    require_fresh(lake, universe, as_of=date.today())

    date_to = lake.latest_date(universe[0])
    if date_to is None:
        raise ValueError(f"No historical data ingested for {universe[0]} -- nothing to backtest")
    date_from = date_to - timedelta(days=DEFAULT_BACKTEST_LOOKBACK_DAYS)

    outcome = run_real_backtest(
        state.python_code.code,
        universe=universe,
        date_from=date_from,
        date_to=date_to,
        config={"init_cash": DEFAULT_INITIAL_CAPITAL},
    )
    if not outcome.passed:
        raise ValueError(f"Real backtest failed: {outcome.error}")

    total_trades = outcome.metrics.get("total_trades")
    metrics = BacktestMetrics(
        sharpe_ratio=outcome.metrics.get("sharpe_ratio") or 0.0,
        sortino_ratio=outcome.metrics.get("sortino_ratio"),
        calmar_ratio=outcome.metrics.get("calmar_ratio"),
        max_drawdown=outcome.metrics.get("max_drawdown") or 0.0,
        cagr=outcome.metrics.get("cagr"),
        win_rate=outcome.metrics.get("win_rate"),
        profit_factor=outcome.metrics.get("profit_factor"),
        expectancy=outcome.metrics.get("expectancy"),
        total_trades=int(total_trades) if total_trades is not None else None,
        data_adjusted=outcome.data_adjusted,
        provider_used=outcome.provider_used,
        data_retrieved_at=outcome.data_retrieved_at,
    )
    equity_curve = [EquityCurvePoint(date=p.date, equity=p.equity) for p in outcome.equity_curve]
    # REL-024: real per-window Walk-Forward input for the Optimization Agent, from this same
    # backtest run's outcome -- empty for a pre-v3-contract strategy (outcome.entries_exits==[]),
    # honestly so rather than fabricated.
    entries_exits = [
        EntryExitSignal(date=p.date, entry=p.entry, exit=p.exit) for p in outcome.entries_exits
    ]
    close_curve = [ClosePricePoint(date=p.date, close=p.close) for p in outcome.close_curve]
    return {
        "backtest_metrics": metrics,
        "equity_curve": equity_curve,
        "entries_exits": entries_exits,
        "close_curve": close_curve,
    }
