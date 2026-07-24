"""Real backtest execution (Phase 4 Epic E4.3): runs a persisted strategy's code against real
historical prices from the data lake, through the exact same sandbox boundary Phase 3's
validation path uses (src/engine/sandbox/runner.py), rather than a separate "trusted" execution
path.

The generated code's return-value contract (`{"metrics": {...}, "equity_curve": [...]}`) is
specified in the PMPT-004 v2 prompt (src/agents/prompts/python_code_generator_agent/v2.md), not
enforced by any type system the LLM is bound to -- this module parses the result defensively:
missing or malformed fields become `None`/an empty list rather than crashing the run or
fabricating a number, matching the fallback-on-failure pattern used throughout src/agents/nodes/.
"""

import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from src.core.config import get_settings
from src.data.datalake.query import DataLake
from src.engine.sandbox.runner import DEFAULT_TIMEOUT_SECONDS, execute_in_sandbox

REAL_BACKTEST_TIMEOUT_SECONDS = 120.0

_METRIC_KEYS = (
    "sharpe_ratio",
    "sortino_ratio",
    "calmar_ratio",
    "max_drawdown",
    "cagr",
    "win_rate",
    "profit_factor",
    "expectancy",
    "total_trades",
)


@dataclass(frozen=True)
class EquityPoint:
    date: str
    equity: float


@dataclass(frozen=True)
class RealBacktestOutcome:
    passed: bool
    error: str | None
    symbol_used: str
    metrics: dict[str, float | int | None] = field(default_factory=dict)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    duration_seconds: float = 0.0


def _extract_metrics(raw: Any) -> dict[str, float | int | None]:
    if not isinstance(raw, dict):
        return {}
    metrics: dict[str, float | int | None] = {}
    for key in _METRIC_KEYS:
        value = raw.get(key)
        if isinstance(value, bool):
            continue  # bool is a subclass of int; not a real metric value
        if isinstance(value, int | float):
            metrics[key] = value
    return metrics


def _extract_equity_curve(raw: Any) -> list[EquityPoint]:
    if not isinstance(raw, list):
        return []
    points = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        d, e = item.get("date"), item.get("equity")
        if isinstance(d, str) and isinstance(e, int | float) and not isinstance(e, bool):
            points.append(EquityPoint(date=d, equity=float(e)))
    return points


def run_real_backtest(
    code: str,
    *,
    universe: list[str],
    date_from: date,
    date_to: date,
    config: dict[str, Any] | None = None,
) -> RealBacktestOutcome:
    """Runs `code` (a persisted StrategyVersion's `run_backtest(data, config)`) against real
    OHLCV for the first symbol in `universe` -- multi-symbol portfolio aggregation isn't
    implemented anywhere else in the codebase either (the backtest engine and the sandbox
    contract both take a single price series), so this deliberately doesn't invent it here."""
    if not universe:
        return RealBacktestOutcome(
            passed=False, error="strategy has an empty universe -- nothing to backtest", symbol_used=""
        )
    symbol = universe[0]

    lake = DataLake(get_settings().data_lake_root / "ohlcv_daily")
    data = lake.read_symbol(symbol, start=date_from, end=date_to)
    if data.height == 0:
        return RealBacktestOutcome(
            passed=False,
            error=f"no historical data ingested for {symbol} in [{date_from}, {date_to}]",
            symbol_used=symbol,
        )

    with tempfile.TemporaryDirectory() as tmpdir_str:
        data_path = Path(tmpdir_str) / f"{symbol}.parquet"
        data.write_parquet(data_path)

        result = execute_in_sandbox(
            code,
            config,
            timeout=max(REAL_BACKTEST_TIMEOUT_SECONDS, DEFAULT_TIMEOUT_SECONDS),
            data_path=data_path,
        )

    if not result.passed:
        return RealBacktestOutcome(
            passed=False, error=result.error, symbol_used=symbol, duration_seconds=result.duration_seconds
        )

    summary = result.portfolio_summary or {}
    return RealBacktestOutcome(
        passed=True,
        error=None,
        symbol_used=symbol,
        metrics=_extract_metrics(summary.get("metrics")),
        equity_curve=_extract_equity_curve(summary.get("equity_curve")),
        duration_seconds=result.duration_seconds,
    )


def write_equity_curve_parquet(outcome: RealBacktestOutcome, *, backtest_result_id: str) -> Path | None:
    """Persists the equity curve to the data lake's equity_curves/ area (sibling to ohlcv_daily/,
    same DataLake root) so BacktestResult.equity_curve_path points at a real, readable file --
    that column existed but nothing ever set it (see agents.py's module docstring for the same
    pattern applied to AgentRun/AgentLog). Returns None if there's no curve to write, rather
    than writing an empty file."""
    if not outcome.equity_curve:
        return None
    root = get_settings().data_lake_root.parent / "equity_curves"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{backtest_result_id}.parquet"
    pl.DataFrame(
        {
            "date": [p.date for p in outcome.equity_curve],
            "equity": [p.equity for p in outcome.equity_curve],
        }
    ).write_parquet(path)
    return path
