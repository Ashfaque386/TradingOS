"""Monte Carlo trade-sequence resampling tests (Phase 3 Epic E3.3), per
Phase_6_Trading_Engine_Design.md §3: 10,000x resampling, 95th-percentile Max Drawdown as the
governing risk metric instead of the historical Max Drawdown.
"""

import numpy as np
import pytest

from src.engine.optimization.monte_carlo import (
    DEFAULT_N_SIMULATIONS,
    max_drawdown_from_returns,
    run_monte_carlo_simulation,
)


def test_max_drawdown_from_returns_manual_reference():
    # equity: 1.0 -> 1.1 -> 0.88 -> 0.924. Peak is 1.1 (after trade 1); worst drawdown is at
    # trade 2: (1.1 - 0.88) / 1.1 = 0.2 exactly.
    returns = np.array([0.1, -0.2, 0.05])
    assert max_drawdown_from_returns(returns) == pytest.approx(0.2, abs=1e-9)


def test_max_drawdown_from_returns_catches_a_first_trade_loss():
    # A loss on the very first trade must register against the implicit starting equity of
    # 1.0, not be masked because there's no earlier point in the array to compare against.
    returns = np.array([-0.3, 0.1, 0.1])
    assert max_drawdown_from_returns(returns) == pytest.approx(0.3, abs=1e-9)


def test_max_drawdown_from_returns_empty_sequence_is_zero():
    assert max_drawdown_from_returns(np.array([])) == 0.0


def test_run_monte_carlo_simulation_default_is_10000_paths():
    returns = [0.05, -0.03, 0.02, -0.08, 0.01, 0.04, -0.02]
    result = run_monte_carlo_simulation(returns, seed=42)

    assert DEFAULT_N_SIMULATIONS == 10_000
    assert result.n_simulations == 10_000
    assert len(result.simulated_max_drawdowns) == 10_000
    assert 0.0 <= result.percentile_95_max_drawdown <= 1.0


def test_run_monte_carlo_simulation_is_deterministic_given_a_seed():
    returns = [0.05, -0.03, 0.02, -0.08, 0.01, 0.04, -0.02]
    result_a = run_monte_carlo_simulation(returns, n_simulations=500, seed=7)
    result_b = run_monte_carlo_simulation(returns, n_simulations=500, seed=7)

    assert result_a.percentile_95_max_drawdown == result_b.percentile_95_max_drawdown
    assert np.array_equal(result_a.simulated_max_drawdowns, result_b.simulated_max_drawdowns)


def test_95th_percentile_is_worse_than_a_luckily_ordered_historical_sequence():
    # The historical order here is the "lucky" one: 9 small wins land first and build a
    # cushion, and the one big loss (-50%) comes last, so the historical Max Drawdown is
    # driven only by that final trade. Most of the 10,000 resampled orderings put that same
    # -50% trade somewhere earlier (before the cushion exists), producing a materially worse
    # drawdown -- exactly the "bad luck in sequencing" risk Phase_6 §3 wants surfaced.
    returns = [0.05] * 9 + [-0.5]
    result = run_monte_carlo_simulation(returns, seed=123)

    assert result.is_worse_than_historical
    assert result.percentile_95_max_drawdown > result.historical_max_drawdown


def test_run_monte_carlo_simulation_empty_trade_sequence():
    result = run_monte_carlo_simulation([], seed=1)

    assert result.historical_max_drawdown == 0.0
    assert result.percentile_95_max_drawdown == 0.0
    assert len(result.simulated_max_drawdowns) == 0
