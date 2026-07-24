"""Correlation constraint (Phase 3 Epic E3.4), per Phase_6_Trading_Engine_Design.md §4 -- part
of the **hardcoded** Risk & Portfolio Engine:

  "Correlation Constraints: Rejects new trades if they increase the portfolio's correlation to
  the broader Nifty 50 beyond 0.85, forcing the AI to find uncorrelated alpha."

A candidate trade is evaluated by simulating what the portfolio's return series would look like
if `candidate_weight` of capital were shifted from the existing portfolio into the candidate
(funded pro-rata from the existing book, not added on top of it -- adding a trade means
reallocating capital, not creating capital), then checking that combined series' correlation to
the benchmark against the configured limit.
"""

from dataclasses import dataclass

import pandas as pd

DEFAULT_NIFTY_CORRELATION_LIMIT = 0.85


@dataclass(frozen=True)
class CorrelationCheckResult:
    correlation: float
    limit: float

    @property
    def passed(self) -> bool:
        return self.correlation <= self.limit


def simulate_combined_portfolio_returns(
    existing_returns: pd.Series, candidate_returns: pd.Series, candidate_weight: float
) -> pd.Series:
    """The portfolio's return series if `candidate_weight` (0-1) of capital is reallocated from
    the existing book into the candidate trade; the remaining `1 - candidate_weight` continues
    to earn the existing portfolio's returns."""
    if not 0.0 <= candidate_weight <= 1.0:
        raise ValueError(f"candidate_weight must be in [0, 1], got {candidate_weight}")
    return (1 - candidate_weight) * existing_returns + candidate_weight * candidate_returns


def check_correlation_constraint(
    existing_portfolio_returns: pd.Series,
    candidate_returns: pd.Series,
    benchmark_returns: pd.Series,
    candidate_weight: float,
    *,
    limit: float = DEFAULT_NIFTY_CORRELATION_LIMIT,
) -> CorrelationCheckResult:
    """Rejects (via `.passed`) a candidate trade whose simulated combined portfolio would
    correlate with `benchmark_returns` (e.g. Nifty 50) beyond `limit`."""
    combined = simulate_combined_portfolio_returns(
        existing_portfolio_returns, candidate_returns, candidate_weight
    )
    correlation = float(combined.corr(benchmark_returns))
    return CorrelationCheckResult(correlation=correlation, limit=limit)
