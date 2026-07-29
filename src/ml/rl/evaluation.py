"""REL-008 E8.4: evaluates a trained RL policy against the existing VectorBT backtesting engine
(AGT-018's own design-doc requirement: "evaluate the resulting policy against the standard
VectorBT-based backtesting environment to ensure consistency between the RL training environment
and real trading conditions, since a policy that only performs well inside its own simulator is
not trustworthy").

Runs the policy deterministically through a `TradingEnv` to collect its real target-weight
sequence, then feeds that sequence into `vbt.Portfolio.from_orders(..., size_type="targetpercent",
group_by=True, cash_sharing=True)` -- a genuinely independent re-simulation via a different code
path (vectorbt, not this project's own env.py step loop), computed via
`src/engine/backtest/metrics.py::compute_metrics()`, the exact same function `backtesting_node`
already uses for rule-based strategies -- RL and supervised/rule-based strategies are judged by
identical, already-tested machinery.
"""

import pandas as pd
import vectorbt as vbt
from stable_baselines3.common.base_class import BaseAlgorithm

from src.agents.state import BacktestMetrics
from src.engine.backtest.metrics import compute_metrics
from src.ml.rl.env import TradingEnv


def evaluate_policy_backtest(policy: BaseAlgorithm, env: TradingEnv) -> BacktestMetrics:
    obs, _info = env.reset()
    weight_rows: list[list[float]] = []
    dates = env.dates[:-1]  # last date has no next-day return, env.step() never uses it as obs
    closes = env.closes

    terminated = False
    while not terminated:
        action, _state = policy.predict(obs, deterministic=True)
        obs, _reward, terminated, _truncated, info = env.step(action)
        # The env's actually-applied weights (post clip/renormalize), not the raw policy action
        # -- see env.step()'s `applied_weights` docstring for why these can differ.
        weight_rows.append([float(w) for w in info["applied_weights"]])

    close = pd.DataFrame(
        {symbol: closes[symbol][: len(weight_rows)] for symbol in env.symbols},
        index=pd.to_datetime(dates[: len(weight_rows)]),
    )
    weights = pd.DataFrame(weight_rows, columns=env.symbols, index=close.index)

    portfolio = vbt.Portfolio.from_orders(
        close,
        size=weights,
        size_type="targetpercent",
        group_by=True,
        cash_sharing=True,
        init_cash=env.initial_cash,
        freq="D",
    )
    return compute_metrics(portfolio)
