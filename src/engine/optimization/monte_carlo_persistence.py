"""Persists a Monte Carlo simulation's 95th-percentile Max Drawdown to the real
`BacktestResult` row for its strategy version (Phase 3 Epic E3.3 exit criterion): "Monte Carlo
simulation executes 10,000 resampled paths ... and the 95th-percentile Max Drawdown metric is
computed and stored." (Phase_14_Master_Development_Roadmap.md)
"""

import uuid

from sqlalchemy.orm import Session

from src.models.strategy import BacktestResult


def persist_monte_carlo_p95_max_drawdown(
    session: Session, backtest_result_id: uuid.UUID, p95_max_drawdown: float
) -> BacktestResult:
    """Updates the given `BacktestResult` row (created by the deterministic historical
    backtest, src/engine/backtest/) with the Monte Carlo-derived 95th-percentile Max Drawdown,
    stored alongside (not replacing) the historical `max_drawdown` already on that row."""
    result = session.get(BacktestResult, backtest_result_id)
    if result is None:
        raise ValueError(f"no BacktestResult row with id {backtest_result_id!r}")

    result.monte_carlo_p95_max_drawdown = p95_max_drawdown
    session.commit()
    return result
