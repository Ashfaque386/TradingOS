"""Backtest performance metrics (Phase 3 Epic E3.2), per Phase_6_Trading_Engine_Design.md §2:
"Output Metrics: Sharpe Ratio, Sortino Ratio, Calmar Ratio, Max Drawdown, Win Rate, Profit
Factor, Expectancy" (+ CAGR, named in Phase_4_AI_Agent_Design.md's BacktestMetrics output).

vectorbt's `Portfolio` already computes every one of these from the simulated equity curve and
trade log with its own well-tested (Numba-compiled) implementations, so this module is a thin
adapter onto `BacktestMetrics` (src/agents/state.py) rather than a re-derivation of the formulas.

Sign convention: `vbt.Portfolio.max_drawdown()` returns a negative fraction (e.g. -0.15 for a
15% decline). `BacktestMetrics.max_drawdown` stores the positive magnitude instead, since every
consumer (Evaluator Agent's Sharpe/Max-DD thresholds, the Max Drawdown Kill Switch at a
configurable 15% threshold per Phase_6 §4) compares it as "drawdown exceeds N%", i.e. against a
positive threshold.
"""

import math

import vectorbt as vbt

from src.agents.state import BacktestMetrics


def compute_metrics(portfolio: vbt.Portfolio) -> BacktestMetrics:
    """Builds a `BacktestMetrics` from a simulated `vbt.Portfolio`. Non-finite metrics (NaN when
    a portfolio has zero closed trades; +/-inf for Sharpe/Sortino when the return series has
    zero variance, e.g. an all-cash portfolio) are passed through as `None` rather than as NaN/
    inf, since `BacktestMetrics`'s optional fields are typed `float | None`, not `float`."""
    trades = portfolio.trades

    return BacktestMetrics(
        sharpe_ratio=_none_if_non_finite(portfolio.sharpe_ratio()) or 0.0,
        sortino_ratio=_none_if_non_finite(portfolio.sortino_ratio()),
        calmar_ratio=_none_if_non_finite(portfolio.calmar_ratio()),
        max_drawdown=abs(_none_if_non_finite(portfolio.max_drawdown()) or 0.0),
        cagr=_none_if_non_finite(portfolio.annualized_return()),
        win_rate=_none_if_non_finite(trades.win_rate()),
        profit_factor=_none_if_non_finite(trades.profit_factor()),
        expectancy=_none_if_non_finite(trades.expectancy()),
        total_trades=int(trades.count()),
    )


def _none_if_non_finite(value: float) -> float | None:
    return value if math.isfinite(value) else None
