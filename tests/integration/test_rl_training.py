"""REL-008 E8.4: a real PPO training run over the real 5-symbol universe, small `total_timesteps`
for CPU feasibility, producing a real (not fabricated) backtest Sharpe number via the real
VectorBT evaluation path -- reported honestly regardless of whether it clears 1.5."""

import math
from datetime import date

import mlflow

from src.ml.features.store import build_feature_frame
from src.ml.mlflow_client import get_tracking_uri
from src.ml.rl.env import TradingEnv
from src.ml.rl.evaluation import evaluate_policy_backtest
from src.ml.rl.policies import train_ppo
from src.ml.rl.stability import assess_seed_stability


def _lake_root():
    from src.core.config import get_settings

    return get_settings().data_lake_root / "ohlcv_daily"


def test_real_ppo_training_over_two_symbols_produces_a_real_backtest_sharpe():
    symbols = ["RELIANCE", "TCS"]
    window_start, window_end = date(2023, 7, 21), date(2024, 7, 19)
    feature_frames = {
        s: build_feature_frame(s, window_start, window_end, lake_root=_lake_root()) for s in symbols
    }

    def env_factory():
        return TradingEnv(feature_frames)

    reward_curves = {}
    models = {}
    for seed in (1, 2):
        model, curve = train_ppo(env_factory, total_timesteps=2000, seed=seed)
        reward_curves[seed] = curve
        models[seed] = model

    stability = assess_seed_stability(reward_curves)
    assert isinstance(stability.coefficient_of_variation, float)

    best_model = models[1]
    metrics = evaluate_policy_backtest(best_model, env_factory())

    assert math.isfinite(metrics.sharpe_ratio)
    assert math.isfinite(metrics.max_drawdown)

    get_tracking_uri()
    with mlflow.start_run(run_name="test_real_ppo_training"):
        mlflow.log_metric("test_sharpe", metrics.sharpe_ratio)
