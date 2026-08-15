"""Multi-run backtest comparison math (REL-069, Phase 3 of the analysis/visualization
initiative), extracted so it's independently testable rather than living inline in a router --
mirrors src/agents/analytics.py's own pure-function style from Phase 2.

Return correlation between two backtest runs answers a real question the Comparison Workspace's
KPI table and equity-curve overlay can't: do two strategies tend to win and lose on the same
days? A portfolio of strategies that are all individually strong but highly correlated is far
riskier in aggregate than one whose members diversify each other -- this is the same real-world
diversification question the historical Max Drawdown / Monte Carlo P95 pairing already answers
for a single strategy, just extended across a candidate portfolio of them.
"""

import itertools
from dataclasses import dataclass

import numpy as np

MIN_OVERLAP_DAYS = 10


@dataclass(frozen=True)
class EquityCurveSeries:
    run_id: str
    points: list[tuple[str, float]]  # (date, equity), same shape as EquityCurvePoint


def compute_return_correlation_matrix(
    curves: list[EquityCurveSeries],
) -> dict[tuple[str, str], float | None]:
    """Pairwise Pearson correlation of daily equity-curve returns, keyed by (run_id, run_id)
    (both orderings included so callers can look up either side without re-sorting). A pair is
    `None` -- never a fabricated 0 or 1 -- when fewer than MIN_OVERLAP_DAYS real dates overlap
    between the two runs' curves, e.g. two backtests over non-overlapping historical windows.
    A run's correlation with itself is always exactly 1.0 when it has at least 1 real day-over-
    day return (i.e. at least 2 real equity-curve points)."""
    returns_by_run = {series.run_id: _daily_returns_by_date(series.points) for series in curves}

    result: dict[tuple[str, str], float | None] = {}
    for i, a in enumerate(curves):
        for b in curves[i:]:
            correlation = _pairwise_correlation(returns_by_run[a.run_id], returns_by_run[b.run_id])
            result[(a.run_id, b.run_id)] = correlation
            result[(b.run_id, a.run_id)] = correlation
    return result


def _daily_returns_by_date(points: list[tuple[str, float]]) -> dict[str, float]:
    """Day-over-day pct-change of equity, keyed by the later date of each pair -- so two curves
    can be aligned by real shared calendar dates even when their own start dates differ."""
    ordered = sorted(points, key=lambda p: p[0])
    returns: dict[str, float] = {}
    for (_, prev_equity), (date, equity) in itertools.pairwise(ordered):
        if prev_equity != 0:
            returns[date] = (equity - prev_equity) / prev_equity
    return returns


def _pairwise_correlation(a: dict[str, float], b: dict[str, float]) -> float | None:
    if a is b:
        return 1.0 if len(a) >= 1 else None
    shared_dates = sorted(set(a) & set(b))
    if len(shared_dates) < MIN_OVERLAP_DAYS:
        return None
    a_returns = np.array([a[d] for d in shared_dates])
    b_returns = np.array([b[d] for d in shared_dates])
    if np.std(a_returns) == 0 or np.std(b_returns) == 0:
        return None
    return float(np.corrcoef(a_returns, b_returns)[0, 1])
