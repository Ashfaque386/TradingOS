"""Correlation constraint tests (Phase 3 Epic E3.4), per Phase_6_Trading_Engine_Design.md §4:
"Rejects new trades if they increase the portfolio's correlation to the broader Nifty 50 beyond
0.85, forcing the AI to find uncorrelated alpha."
"""

import numpy as np
import pandas as pd
import pytest

from src.engine.risk.correlation import (
    DEFAULT_NIFTY_CORRELATION_LIMIT,
    check_correlation_constraint,
    simulate_combined_portfolio_returns,
)


def test_simulate_combined_portfolio_returns_is_a_weighted_average():
    existing = pd.Series([0.10, 0.10, 0.10])
    candidate = pd.Series([0.00, 0.00, 0.00])

    combined = simulate_combined_portfolio_returns(existing, candidate, candidate_weight=0.25)

    assert np.allclose(combined.to_numpy(), 0.075)


def test_simulate_combined_portfolio_returns_rejects_out_of_range_weight():
    existing = pd.Series([0.1])
    candidate = pd.Series([0.0])

    with pytest.raises(ValueError):
        simulate_combined_portfolio_returns(existing, candidate, candidate_weight=1.5)


def test_default_correlation_limit_matches_design_doc():
    assert DEFAULT_NIFTY_CORRELATION_LIMIT == 0.85


def test_rejects_a_candidate_highly_correlated_with_the_benchmark():
    rng = np.random.default_rng(0)
    benchmark = pd.Series(rng.normal(0, 1, 200))
    # Nearly identical to the benchmark (tiny idiosyncratic noise) -> correlation ~1.0.
    candidate = benchmark + rng.normal(0, 0.01, 200)
    existing = pd.Series(rng.normal(0, 1, 200))  # unrelated existing book

    result = check_correlation_constraint(existing, candidate, benchmark, candidate_weight=1.0)

    assert result.correlation > 0.85
    assert result.passed is False


def test_passes_a_candidate_uncorrelated_with_the_benchmark():
    rng = np.random.default_rng(1)
    benchmark = pd.Series(rng.normal(0, 1, 200))
    candidate = pd.Series(rng.normal(0, 1, 200))  # independent draw -> ~uncorrelated
    existing = pd.Series(rng.normal(0, 1, 200))

    result = check_correlation_constraint(existing, candidate, benchmark, candidate_weight=1.0)

    assert abs(result.correlation) < 0.85
    assert result.passed is True


def test_partial_allocation_dilutes_correlation_toward_the_existing_book():
    rng = np.random.default_rng(2)
    benchmark = pd.Series(rng.normal(0, 1, 200))
    candidate = benchmark + rng.normal(0, 0.01, 200)  # highly correlated candidate
    existing = pd.Series(rng.normal(0, 1, 200))  # uncorrelated existing book

    full_allocation = check_correlation_constraint(existing, candidate, benchmark, 1.0)
    small_allocation = check_correlation_constraint(existing, candidate, benchmark, 0.05)

    assert small_allocation.correlation < full_allocation.correlation
