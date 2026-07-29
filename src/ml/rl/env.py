"""REL-008 E8.4: a real Gymnasium-compatible trading environment (Phase_5 §4's "Custom OpenAI
Gym environment simulating the Indian stock market, including STT and Zerodha brokerage logic").

State space -- documented honestly: cash fraction (1) + current portfolio weights (n_symbols) +
this codebase's real engineered features per symbol (n_symbols * len(FEATURE_COLUMNS)). Phase_5's
"top 20 market features" framing is aspirational against this codebase's real ~11-column Feature
Store; the actual vector width below is whatever build_feature_frame() genuinely produces, not
padded to a fabricated 20.

Costs: real Zerodha-style delivery-segment brokerage/STT/exchange/SEBI/stamp-duty/GST, computed
per rebalanced leg via the existing src/engine/backtest/friction.py::compute_trade_cost() --
reused directly, not reinvented.

Reward: rolling-20-day Sharpe of the daily portfolio return, minus a turnover penalty
(`turnover_penalty_coef * L1(delta weights)`) -- a concrete formula chosen and documented here,
since Phase_5 §4 only specifies the qualitative shape ("Risk-adjusted return (Sharpe Ratio) minus
a penalty for excessive turnover").
"""

from collections import deque
from datetime import date
from typing import Any, Literal

import gymnasium as gym
import numpy as np
import polars as pl
from gymnasium import spaces

from src.engine.backtest.friction import compute_trade_cost
from src.ml.features.store import FEATURE_COLUMNS

SHARPE_WINDOW = 20
TURNOVER_PENALTY_COEF = 0.5
TRADING_DAYS_PER_YEAR = 252


class TradingEnv(gym.Env[np.ndarray, np.ndarray]):
    metadata = {"render_modes": []}

    def __init__(
        self,
        feature_frames: dict[str, pl.DataFrame],
        *,
        initial_cash: float = 100_000.0,
        turnover_penalty_coef: float = TURNOVER_PENALTY_COEF,
    ) -> None:
        super().__init__()
        if not feature_frames:
            raise ValueError("feature_frames must be non-empty")

        self.symbols = sorted(feature_frames.keys())
        self.n_symbols = len(self.symbols)
        self.initial_cash = initial_cash
        self.turnover_penalty_coef = turnover_penalty_coef

        # Align every symbol's frame to the common date intersection -- a real, deterministic
        # step index every symbol has a price/feature row for.
        common_dates: set[date] | None = None
        for df in feature_frames.values():
            dates = set(df["date"].to_list())
            common_dates = dates if common_dates is None else common_dates & dates
        self._dates: list[date] = sorted(common_dates or set())
        if len(self._dates) < 2:
            raise ValueError("fewer than 2 common trading days across the given symbols")

        self._closes: dict[str, list[float]] = {}
        self._features: dict[str, list[list[float]]] = {}
        for symbol, df in feature_frames.items():
            aligned = df.filter(pl.col("date").is_in(self._dates)).sort("date")
            self._closes[symbol] = aligned["close"].to_list()
            self._features[symbol] = aligned.select(FEATURE_COLUMNS).to_numpy().tolist()

        self._obs_dim = 1 + self.n_symbols + self.n_symbols * len(FEATURE_COLUMNS)
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(self._obs_dim,))
        self.action_space = spaces.Box(low=0.0, high=1.0, shape=(self.n_symbols,))

        self._step_index = 0
        self._weights = np.zeros(self.n_symbols)
        self._portfolio_value = initial_cash
        self._return_history: deque[float] = deque(maxlen=SHARPE_WINDOW)

    @property
    def dates(self) -> list[date]:
        """The real trading dates (aligned across every symbol) this episode steps through."""
        return list(self._dates)

    @property
    def closes(self) -> dict[str, list[float]]:
        """Real per-symbol closing prices, aligned to `dates` -- read-only outside this class."""
        return {symbol: list(prices) for symbol, prices in self._closes.items()}

    def _observation(self) -> np.ndarray:
        cash_fraction = 1.0 - float(self._weights.sum())
        features = np.concatenate([self._features[s][self._step_index] for s in self.symbols])
        return np.concatenate([[cash_fraction], self._weights, features]).astype(np.float32)

    def reset(
        self, *, seed: int | None = None, options: dict[str, Any] | None = None
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)
        self._step_index = 0
        self._weights = np.zeros(self.n_symbols)
        self._portfolio_value = self.initial_cash
        self._return_history.clear()
        return self._observation(), {}

    def step(self, action: np.ndarray) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        target_weights = np.clip(np.asarray(action, dtype=np.float64), 0.0, 1.0)
        weight_sum = target_weights.sum()
        if weight_sum > 1.0:
            target_weights = target_weights / weight_sum  # renormalize an oversubscribed action

        delta_weights = target_weights - self._weights
        total_cost = 0.0
        for i, symbol in enumerate(self.symbols):
            trade_value = abs(delta_weights[i]) * self._portfolio_value
            if trade_value <= 0:
                continue
            side: Literal["buy", "sell"] = "buy" if delta_weights[i] > 0 else "sell"
            price = self._closes[symbol][self._step_index]
            quantity = trade_value / price if price > 0 else 0.0
            cost = compute_trade_cost(price, quantity, segment="delivery", side=side)
            total_cost += cost.total

        value_after_costs = self._portfolio_value - total_cost
        self._weights = target_weights

        next_index = self._step_index + 1
        terminated = next_index >= len(self._dates) - 1

        # Apply next day's price move to the newly-rebalanced weights.
        if not terminated:
            day_return = sum(
                target_weights[i]
                * (
                    (self._closes[symbol][next_index] - self._closes[symbol][self._step_index])
                    / self._closes[symbol][self._step_index]
                )
                for i, symbol in enumerate(self.symbols)
            )
        else:
            day_return = 0.0

        new_portfolio_value = value_after_costs * (1.0 + day_return)
        portfolio_return = (
            (new_portfolio_value - self._portfolio_value) / self._portfolio_value
            if self._portfolio_value > 0
            else 0.0
        )
        self._portfolio_value = new_portfolio_value
        self._return_history.append(portfolio_return)

        turnover = float(np.abs(delta_weights).sum())
        reward = self._compute_reward(turnover)

        self._step_index = next_index
        obs = self._observation() if not terminated else np.zeros(self._obs_dim, dtype=np.float32)
        info: dict[str, Any] = {
            "portfolio_value": self._portfolio_value,
            "turnover": turnover,
            "cost": total_cost,
            # The actually-applied weights, post clip/renormalize -- may differ from the raw
            # `action` passed in (e.g. an oversubscribed action gets renormalized to sum to 1).
            # Consumers needing "what did the env really do this step" (e.g. evaluation.py's
            # independent vectorbt re-simulation) must use this, not the raw action.
            "applied_weights": target_weights.copy(),
        }
        return obs, reward, terminated, False, info

    def _compute_reward(self, turnover: float) -> float:
        returns = np.array(self._return_history)
        if len(returns) >= 2 and returns.std() > 0:
            sharpe = (returns.mean() / returns.std()) * np.sqrt(TRADING_DAYS_PER_YEAR)
        else:
            sharpe = float(returns[-1]) if len(returns) else 0.0
        return float(sharpe - self.turnover_penalty_coef * turnover)
