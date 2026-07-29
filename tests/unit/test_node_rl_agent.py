from contextlib import ExitStack
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from src.agents.nodes.rl_agent import RLTrainingRejected, rl_agent_node
from src.agents.state import RLTrainingRequest, TradingOSGraphState
from src.data.features.indicators import macd, with_indicators
from src.ml.features.store import FEATURE_COLUMNS, rolling_vwap


def _synthetic_feature_frame(closes: list[float]) -> pl.DataFrame:
    start = date(2024, 1, 1)
    raw = pl.DataFrame(
        {
            "symbol": ["TEST"] * len(closes),
            "date": [start + timedelta(days=i) for i in range(len(closes))],
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1000] * len(closes),
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


_REQUEST = RLTrainingRequest(
    algorithm="PPO",
    symbols=["A", "B"],
    window_start="2024-01-01",
    window_end="2024-03-01",
    total_timesteps=100,
    seeds=[1, 2, 3],
)


def _fake_response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices[0].message.content = content
    return response


def _fake_session_cm():
    cm = MagicMock()
    cm.__enter__.return_value = MagicMock()
    cm.__exit__.return_value = False
    return cm


def _state() -> TradingOSGraphState:
    return TradingOSGraphState(thread_id="t1", rl_training_request=_REQUEST)


def _patched(*, stability_reward_curves, backtest_sharpe=2.0):
    frame_a = _synthetic_feature_frame([100.0 + i for i in range(60)])
    frame_b = _synthetic_feature_frame([200.0 + i * 0.5 for i in range(60)])

    def fake_build_feature_frame(symbol, *_args, **_kwargs):
        return frame_a if symbol == "A" else frame_b

    fake_backtest_metrics = MagicMock()
    fake_backtest_metrics.sharpe_ratio = backtest_sharpe

    fake_ml_model = MagicMock()
    fake_ml_model.id = "ml-model-id"

    fake_mlflow = MagicMock()
    fake_run = MagicMock()
    fake_run.info.run_id = "fake-mlflow-run-id"
    fake_mlflow.start_run.return_value.__enter__.return_value = fake_run

    return (
        patch(
            "src.agents.nodes.rl_agent.build_feature_frame", side_effect=fake_build_feature_frame
        ),
        patch(
            "src.agents.nodes.rl_agent.train_policy",
            side_effect=lambda algorithm, env_factory, total_timesteps, seed: (
                MagicMock(),
                stability_reward_curves[seed],
            ),
        ),
        patch(
            "src.agents.nodes.rl_agent.evaluate_policy_backtest",
            return_value=fake_backtest_metrics,
        ),
        patch("src.agents.nodes.rl_agent.get_tracking_uri", return_value="http://fake:5000"),
        patch("src.agents.nodes.rl_agent.mlflow", fake_mlflow),
        patch("src.agents.nodes.rl_agent.get_session", return_value=_fake_session_cm()),
        patch("src.agents.nodes.rl_agent.sync_mlflow_run_to_ml_models", return_value=fake_ml_model),
    )


def test_rl_agent_node_requires_rl_training_request():
    with pytest.raises(ValueError):
        rl_agent_node(TradingOSGraphState(thread_id="t1"))


def test_rl_agent_node_returns_a_real_result_when_stable():
    stable_curves = {1: [1.0, 1.05, 1.02], 2: [1.0, 1.03, 1.01], 3: [1.0, 1.04, 1.02]}
    narrative_json = '{"narrative": "Stable PPO run, good backtest Sharpe."}'

    with ExitStack() as stack:
        for p in _patched(stability_reward_curves=stable_curves):
            stack.enter_context(p)
        stack.enter_context(
            patch("src.agents.nodes.rl_agent.complete", return_value=_fake_response(narrative_json))
        )
        result = rl_agent_node(_state())

    rl_result = result["rl_training_result"]
    assert rl_result.stability_passed is True
    assert rl_result.algorithm == "PPO"
    assert rl_result.backtest_sharpe == 2.0


def test_rl_agent_node_rejects_an_unstable_run():
    unstable_curves = {1: [100.0], 2: [-50.0], 3: [1.0]}

    with ExitStack() as stack:
        for p in _patched(stability_reward_curves=unstable_curves):
            stack.enter_context(p)
        with pytest.raises(RLTrainingRejected):
            rl_agent_node(_state())
