"""Volatility-adjusted position sizing tests (Phase 3 Epic E3.4), per
Phase_6_Trading_Engine_Design.md §4: "equal risk contribution across the portfolio."
"""

import pandas as pd
import pytest

from src.engine.risk.position_sizing import (
    compute_inverse_volatility_weights,
    compute_position_sizes,
    compute_volatility,
)


def test_compute_volatility_matches_pandas_std():
    returns = pd.Series([0.01, -0.02, 0.015, -0.01, 0.02])
    assert compute_volatility(returns) == pytest.approx(returns.std())


def test_compute_volatility_respects_window():
    returns = pd.Series([0.1, 0.1, 0.1, 0.01, -0.02, 0.015, -0.01, 0.02])
    windowed = compute_volatility(returns, window=5)
    assert windowed == pytest.approx(returns.tail(5).std())
    assert windowed != pytest.approx(returns.std())


def test_inverse_volatility_weights_are_proportional_to_1_over_vol():
    # symbol B is exactly twice as volatile as symbol A -> A gets twice B's weight.
    weights = compute_inverse_volatility_weights({"A": 0.02, "B": 0.04})

    assert weights["A"] == pytest.approx(2 / 3)
    assert weights["B"] == pytest.approx(1 / 3)
    assert sum(weights.values()) == pytest.approx(1.0)


def test_inverse_volatility_weights_excludes_zero_and_nonfinite_volatility():
    weights = compute_inverse_volatility_weights({"A": 0.02, "B": 0.0, "C": float("nan")})

    assert "B" not in weights
    assert "C" not in weights
    assert weights["A"] == pytest.approx(1.0)


def test_inverse_volatility_weights_all_zero_volatility_returns_zero_weights():
    weights = compute_inverse_volatility_weights({"A": 0.0, "B": 0.0})
    assert weights == {"A": 0.0, "B": 0.0}


def test_position_sizes_achieve_equal_risk_contribution():
    # A is flat (low vol), B is twice as volatile -- equal risk contribution means
    # weight * volatility should come out equal for every symbol.
    returns_by_symbol = {
        "STABLE": pd.Series([0.005, -0.005, 0.006, -0.004, 0.005]),
        "VOLATILE": pd.Series([0.01, -0.01, 0.012, -0.008, 0.01]),
    }
    prices = {"STABLE": 100.0, "VOLATILE": 100.0}

    results = compute_position_sizes(returns_by_symbol, prices, total_capital=100_000.0)

    risk_contributions = {
        symbol: r.weight * compute_volatility(returns_by_symbol[symbol])
        for symbol, r in results.items()
    }
    assert risk_contributions["STABLE"] == pytest.approx(risk_contributions["VOLATILE"], rel=1e-9)


def test_position_sizes_respect_prices_and_capital():
    returns_by_symbol = {"A": pd.Series([0.01, -0.01, 0.01, -0.01])}
    prices = {"A": 250.0}

    results = compute_position_sizes(returns_by_symbol, prices, total_capital=100_000.0)

    assert results["A"].weight == pytest.approx(1.0)
    assert results["A"].capital_allocation == pytest.approx(100_000.0)
    assert results["A"].shares == 400  # 100,000 / 250, floored to a whole share count
