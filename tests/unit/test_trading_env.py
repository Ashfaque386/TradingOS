from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from src.data.features.indicators import macd, with_indicators
from src.engine.backtest.friction import compute_trade_cost
from src.ml.features.store import FEATURE_COLUMNS, rolling_vwap
from src.ml.rl.env import TradingEnv


def _synthetic_feature_frame(closes: list[float], seed_offset: int = 0) -> pl.DataFrame:
    start = date(2024, 1, 1)
    rng = np.random.default_rng(42 + seed_offset)
    raw = pl.DataFrame(
        {
            "symbol": ["TEST"] * len(closes),
            "date": [start + timedelta(days=i) for i in range(len(closes))],
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": rng.integers(1000, 5000, size=len(closes)).tolist(),
        }
    )
    macd_line, macd_signal, macd_hist = macd(raw)
    engineered = with_indicators(raw).with_columns(
        macd_line.alias("macd_line"),
        macd_signal.alias("macd_signal"),
        macd_hist.alias("macd_hist"),
        rolling_vwap(raw, window=20).alias("vwap_20"),
    )
    return engineered.filter(pl.all_horizontal(pl.col(c).is_not_null() for c in FEATURE_COLUMNS))


def _two_symbol_env() -> TradingEnv:
    rng = np.random.default_rng(1)
    closes_a = list(100 + np.cumsum(rng.normal(0, 1, 60)))
    closes_b = list(200 + np.cumsum(rng.normal(0, 2, 60)))
    frames = {
        "A": _synthetic_feature_frame(closes_a, seed_offset=1),
        "B": _synthetic_feature_frame(closes_b, seed_offset=2),
    }
    return TradingEnv(frames, initial_cash=100_000.0)


def test_reset_returns_observation_matching_declared_space() -> None:
    env = _two_symbol_env()
    obs, info = env.reset()
    assert obs.shape == env.observation_space.shape
    assert info == {}


def test_step_returns_finite_reward_and_matching_shapes() -> None:
    env = _two_symbol_env()
    env.reset()
    action = np.array([0.3, 0.3], dtype=np.float32)
    obs, reward, terminated, truncated, info = env.step(action)

    assert obs.shape == env.observation_space.shape
    assert np.isfinite(reward)
    assert isinstance(terminated, bool)
    assert truncated is False
    assert "portfolio_value" in info


def test_episode_terminates_at_the_end_of_the_data_window() -> None:
    env = _two_symbol_env()
    env.reset()
    terminated = False
    steps = 0
    while not terminated and steps < 1000:
        action = env.action_space.sample()
        _obs, _reward, terminated, _truncated, _info = env.step(action)
        steps += 1
    assert terminated is True
    assert steps == len(env.dates) - 1


def test_brokerage_and_stt_deduction_matches_friction_reference_figures() -> None:
    env = _two_symbol_env()
    env.reset()
    # A full rebalance into symbol A alone forces a real buy-side trade of ~30000 (30% of 100k).
    action = np.array([0.3, 0.0], dtype=np.float32)
    _obs, _reward, _terminated, _truncated, info = env.step(action)

    price = env.closes["A"][0]
    quantity = (0.3 * env.initial_cash) / price
    expected_cost = compute_trade_cost(price, quantity, segment="delivery", side="buy")

    assert info["cost"] == pytest.approx(expected_cost.total, rel=1e-6)


def test_rejects_empty_feature_frames() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        TradingEnv({})
