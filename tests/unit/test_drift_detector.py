import numpy as np
import polars as pl
import pytest

from src.ml.drift.detector import (
    compute_feature_drift,
    compute_rolling_sharpe,
    jensen_shannon_divergence,
)


def test_identical_distributions_have_near_zero_divergence() -> None:
    rng = np.random.default_rng(0)
    sample = rng.normal(0, 1, 500)
    divergence = jensen_shannon_divergence(sample, sample.copy())
    assert divergence == pytest.approx(0.0, abs=1e-6)


def test_disjoint_distributions_have_near_max_divergence() -> None:
    rng = np.random.default_rng(0)
    low = rng.normal(0, 0.1, 500)
    high = rng.normal(100, 0.1, 500)
    divergence = jensen_shannon_divergence(low, high)
    # With the real 3-bin quantile-based binning (calibrated for this project's small real
    # 30-day live samples -- see jensen_shannon_divergence's own docstring), add-one smoothing
    # dilutes the max achievable divergence somewhat; 0.6 is still unambiguously "very high" for
    # two completely disjoint distributions, comfortably above DRIFT_JS_THRESHOLD=0.10.
    assert divergence > 0.6


def test_compute_feature_drift_returns_one_value_per_column() -> None:
    rng = np.random.default_rng(0)
    reference = pl.DataFrame({"rsi_14": rng.normal(50, 5, 100), "atr_14": rng.normal(2, 0.5, 100)})
    live = pl.DataFrame({"rsi_14": rng.normal(50, 5, 30), "atr_14": rng.normal(2, 0.5, 30)})

    result = compute_feature_drift(reference, live, ["rsi_14", "atr_14"])

    assert set(result.keys()) == {"rsi_14", "atr_14"}
    assert all(0.0 <= v <= 1.0 for v in result.values())


def test_compute_rolling_sharpe_matches_hand_computed_value() -> None:
    returns = pl.Series([0.01, 0.02, -0.01, 0.015, 0.005])
    result = compute_rolling_sharpe(returns, window=5)

    mean = returns.mean()
    std = returns.std()
    expected = (mean / std) * (252**0.5)
    assert result == pytest.approx(expected)


def test_compute_rolling_sharpe_is_zero_for_constant_returns() -> None:
    returns = pl.Series([0.01] * 10)
    assert compute_rolling_sharpe(returns, window=10) == 0.0
