"""Real backtest execution (Phase 4 Epic E4.3): runs a persisted strategy's code against real
historical prices from the data lake, through the exact same sandbox boundary Phase 3's
validation path uses (src/engine/sandbox/runner.py), rather than a separate "trusted" execution
path.

The generated code's return-value contract is specified in the PMPT-004 prompt
(src/agents/prompts/python_code_generator_agent/), not enforced by any type system the LLM is
bound to -- this module parses the result defensively: missing or malformed fields become
`None`/an empty list rather than crashing the run or fabricating a number, matching the
fallback-on-failure pattern used throughout src/agents/nodes/.

REL-022 (2026-08-05): the contract was extended from v2's `{"metrics", "equity_curve"}` to v3's
`{"metrics", "equity_curve", "trades", "entries_exits"}` -- a real per-trade ledger and the real
entries/exits signal series the sandboxed code already computes internally to build its
`vbt.Portfolio`, previously discarded. Not retroactive: a `BacktestResult` row created under v2
has `trades=None`, not a backfilled/fabricated list -- there is no way to reconstruct a real
trade ledger from a v2-era result that never captured one.

REL-024 (2026-08-05): `RealBacktestOutcome` also now carries `close_curve` -- the real OHLCV
close price series this function already reads from the data lake before handing it to the
sandbox, previously discarded once the sandbox run completed. Walk-Forward Optimization
(src/engine/optimization/walk_forward_adapter.py) needs real close prices alongside
`entries_exits` to re-run the strategy's own signals against rolling windows; re-reading the
data lake a second time for that would be redundant I/O for data this function already has.

REL-032 (2026-08-08, NFR-01): `run_real_backtest` now executes through `execute_in_pool()`
(src/engine/sandbox/pool.py) instead of the original one-shot `execute_in_sandbox()` -- a warm
sandbox worker pool that cuts real, measured latency from ~9-29s (cold process, every call) to
~0.06s (already-warm process) once a worker has run at least once. See that module's own
docstring for the full research (why numba's on-disk cache alone doesn't solve this) and the
real security tradeoff pooling accepts and mitigates.
"""

import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from src.core.config import get_settings
from src.core.db import get_session
from src.data.datalake.query import DataLake
from src.data.provenance import get_provenance
from src.engine.backtest.corporate_actions_adjust import (
    adjust_ohlcv_for_corporate_actions,
    load_corporate_actions,
)
from src.engine.sandbox.pool import execute_in_pool
from src.engine.sandbox.runner import DEFAULT_TIMEOUT_SECONDS

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


# REL-022: the real per-trade ledger, from PMPT-004 v3's "trades" field (pf.trades.records_readable
# in the sandboxed code). All 8 keys are required per-trade by the v3 contract -- a trade missing
# any of them is dropped rather than persisted half-populated (see _extract_trades below).
@dataclass(frozen=True)
class Trade:
    entry_date: str
    exit_date: str
    side: str
    size: float
    entry_price: float
    exit_price: float
    pnl: float
    return_pct: float


# REL-022: the real entries/exits signal series, from PMPT-004 v3's "entries_exits" field -- the
# same boolean Series the sandboxed code already passed into Portfolio.from_signals, re-surfaced
# for downstream use (REL-024's Walk-Forward adapter) rather than a fabricated approximation.
@dataclass(frozen=True)
class EntryExitPoint:
    date: str
    entry: bool
    exit: bool


# REL-024: the real OHLCV close price series for the requested [date_from, date_to] window --
# read from the data lake before the sandbox even runs, so this is always populated whenever
# real historical data was found, regardless of what the sandboxed code itself returns.
@dataclass(frozen=True)
class ClosePricePoint:
    date: str
    close: float


@dataclass(frozen=True)
class RealBacktestOutcome:
    passed: bool
    error: str | None
    symbol_used: str
    metrics: dict[str, float | int | None] = field(default_factory=dict)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    entries_exits: list[EntryExitPoint] = field(default_factory=list)
    close_curve: list[ClosePricePoint] = field(default_factory=list)
    duration_seconds: float = 0.0
    # REL-072: whether the real split/bonus adjustment pipeline (corporate_actions_adjust.py)
    # was applied to the OHLCV data this outcome is based on -- an honest "was real
    # corporate-action data considered" provenance signal, not "did anything actually change"
    # (a symbol with zero real recorded actions still gets data_adjusted=True when the flag was
    # on, since the pipeline genuinely ran and genuinely found nothing to adjust).
    data_adjusted: bool = False
    # REL-073: real reproducibility provenance, from src/models/market_data_provenance.py's own
    # one-row-per-symbol record of the most recent managed/scheduled ingestion. Both None (never
    # guessed) when this symbol has no such record -- e.g. only ever ingested via the direct
    # bhavcopy/yfinance CLI adapters, which bypass MarketDataManager entirely.
    provider_used: str | None = None
    data_retrieved_at: datetime | None = None


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


def _extract_trades(raw: Any) -> list[Trade]:
    """REL-022. A trade missing any of the 8 required keys, or with the wrong type for one, is
    dropped rather than persisted half-populated -- same defensive posture as every other
    extractor in this module: a v2-era strategy (no "trades" key at all) or a malformed v3
    response both fall through to an empty list, not a crash or a fabricated trade."""
    if not isinstance(raw, list):
        return []
    trades = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        entry_date, exit_date, side = (
            item.get("entry_date"),
            item.get("exit_date"),
            item.get("side"),
        )
        size, entry_price, exit_price = (
            item.get("size"),
            item.get("entry_price"),
            item.get("exit_price"),
        )
        pnl, return_pct = item.get("pnl"), item.get("return_pct")
        if not (
            isinstance(entry_date, str)
            and isinstance(exit_date, str)
            and isinstance(side, str)
            and isinstance(size, int | float)
            and not isinstance(size, bool)
            and isinstance(entry_price, int | float)
            and not isinstance(entry_price, bool)
            and isinstance(exit_price, int | float)
            and not isinstance(exit_price, bool)
            and isinstance(pnl, int | float)
            and not isinstance(pnl, bool)
            and isinstance(return_pct, int | float)
            and not isinstance(return_pct, bool)
        ):
            continue
        trades.append(
            Trade(
                entry_date=entry_date,
                exit_date=exit_date,
                side=side,
                size=float(size),
                entry_price=float(entry_price),
                exit_price=float(exit_price),
                pnl=float(pnl),
                return_pct=float(return_pct),
            )
        )
    return trades


def _close_curve_from_data(data: pl.DataFrame) -> list[ClosePricePoint]:
    """REL-024. Unlike the other extractors, `data` is this function's own real data lake read
    (src/data/datalake/query.py's fixed `date`/`close` schema), not an LLM-controlled return
    value -- no defensive type-narrowing needed, matching how the rest of this module already
    trusts its own DataLake reads."""
    return [
        ClosePricePoint(date=str(row["date"]), close=float(row["close"]))
        for row in data.iter_rows(named=True)
    ]


def _extract_entries_exits(raw: Any) -> list[EntryExitPoint]:
    """REL-022. Same defensive posture as _extract_trades/_extract_equity_curve."""
    if not isinstance(raw, list):
        return []
    points = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        d, entry, exit_ = item.get("date"), item.get("entry"), item.get("exit")
        if isinstance(d, str) and isinstance(entry, bool) and isinstance(exit_, bool):
            points.append(EntryExitPoint(date=d, entry=entry, exit=exit_))
    return points


def run_real_backtest(
    code: str,
    *,
    universe: list[str],
    date_from: date,
    date_to: date,
    config: dict[str, Any] | None = None,
    adjust_for_corporate_actions: bool = True,
) -> RealBacktestOutcome:
    """Runs `code` (a persisted StrategyVersion's `run_backtest(data, config)`) against real
    OHLCV for the first symbol in `universe` -- multi-symbol portfolio aggregation isn't
    implemented anywhere else in the codebase either (the backtest engine and the sandbox
    contract both take a single price series), so this deliberately doesn't invent it here.

    REL-072: `adjust_for_corporate_actions` defaults to `True`, matching
    `src/engine/backtest/data_feed.py`'s own already-documented rationale -- an un-adjusted
    backtest over a symbol with a real historical split/bonus is the wrong number by default,
    not a valid alternative mode a caller would deliberately choose."""
    if not universe:
        return RealBacktestOutcome(
            passed=False,
            error="strategy has an empty universe -- nothing to backtest",
            symbol_used="",
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

    # REL-073: real reproducibility provenance -- the most recent managed/scheduled ingestion's
    # provider/fetch-time for this symbol, if any (None, never guessed, when this symbol has only
    # ever been touched by the direct bhavcopy/yfinance CLI adapters, which bypass
    # MarketDataManager entirely and so never write a provenance row).
    with get_session() as session:
        provenance = get_provenance(session, symbol)
        if adjust_for_corporate_actions:
            # REL-072: closes the real gap this codebase's own corporate_actions_adjust.py
            # stated -- a real, tested adjustment pipeline already used correctly by
            # data_feed.py's own _maybe_adjust, but with zero real callers on this actual
            # backtest execution path until now. Same pandas conversion _maybe_adjust already
            # performs, reused verbatim rather than duplicated.
            actions = load_corporate_actions(session, symbol)
    provider_used = provenance.provider if provenance else None
    data_retrieved_at = provenance.retrieved_at if provenance else None

    if adjust_for_corporate_actions:
        # Cast back to the exact original Polars schema/dtypes so nothing downstream (the
        # sandbox, write_parquet, _close_curve_from_data below) sees a different shape.
        pandas_df = data.to_pandas().set_index("date").sort_index()
        pandas_df = adjust_ohlcv_for_corporate_actions(pandas_df, actions)
        data = (
            pl.from_pandas(pandas_df.reset_index())
            .with_columns(pl.col("date").cast(pl.Date))
            .select(["symbol", "date", "open", "high", "low", "close", "volume"])
        )

    with tempfile.TemporaryDirectory() as tmpdir_str:
        data_path = Path(tmpdir_str) / f"{symbol}.parquet"
        data.write_parquet(data_path)

        # REL-032 (NFR-01): the warm sandbox pool, not the original one-shot execute_in_sandbox()
        # -- see src/engine/sandbox/pool.py's own module docstring for why (real, measured
        # ~9-29s-cold vs ~0.06s-warm latency) and what changes about the security model. Falls
        # back to execute_in_sandbox() automatically if the pool is disabled or fails.
        result = execute_in_pool(
            code,
            config,
            timeout=max(REAL_BACKTEST_TIMEOUT_SECONDS, DEFAULT_TIMEOUT_SECONDS),
            data_path=data_path,
        )

    if not result.passed:
        return RealBacktestOutcome(
            passed=False,
            error=result.error,
            symbol_used=symbol,
            duration_seconds=result.duration_seconds,
            data_adjusted=adjust_for_corporate_actions,
            provider_used=provider_used,
            data_retrieved_at=data_retrieved_at,
        )

    summary = result.portfolio_summary or {}
    return RealBacktestOutcome(
        passed=True,
        error=None,
        symbol_used=symbol,
        metrics=_extract_metrics(summary.get("metrics")),
        equity_curve=_extract_equity_curve(summary.get("equity_curve")),
        trades=_extract_trades(summary.get("trades")),
        entries_exits=_extract_entries_exits(summary.get("entries_exits")),
        close_curve=_close_curve_from_data(data),
        duration_seconds=result.duration_seconds,
        data_adjusted=adjust_for_corporate_actions,
        provider_used=provider_used,
        data_retrieved_at=data_retrieved_at,
    )


def write_equity_curve_parquet(
    outcome: RealBacktestOutcome, *, backtest_result_id: str
) -> Path | None:
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
