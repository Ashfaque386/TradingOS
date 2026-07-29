"""REL-008 E8.4: PPO + SAC training (Phase_5 §4), via `stable-baselines3` directly rather than
FinRL -- see the REL-008 plan's "decisions made without asking" section for why (FinRL's own
pins fight this project's newer pandas/numpy; SB3 is what FinRL wraps anyway)."""

from collections.abc import Callable
from typing import Literal

import gymnasium as gym
import numpy as np
from stable_baselines3 import PPO, SAC
from stable_baselines3.common.callbacks import BaseCallback


class _RewardCurveCallback(BaseCallback):
    """Records per-episode total reward -- the raw material `stability.py::assess_seed_stability`
    compares across seeds."""

    def __init__(self) -> None:
        super().__init__()
        self.episode_rewards: list[float] = []
        self._current_episode_reward = 0.0

    def _on_step(self) -> bool:
        rewards = self.locals.get("rewards", [0.0])
        dones = self.locals.get("dones", [False])
        self._current_episode_reward += float(rewards[0])
        if dones[0]:
            self.episode_rewards.append(self._current_episode_reward)
            self._current_episode_reward = 0.0
        return True


def train_ppo(
    env_factory: Callable[[], gym.Env[np.ndarray, np.ndarray]], total_timesteps: int, seed: int
) -> tuple[PPO, list[float]]:
    env = env_factory()
    model = PPO("MlpPolicy", env, seed=seed, verbose=0)
    callback = _RewardCurveCallback()
    model.learn(total_timesteps=total_timesteps, callback=callback)
    return model, callback.episode_rewards


def train_sac(
    env_factory: Callable[[], gym.Env[np.ndarray, np.ndarray]], total_timesteps: int, seed: int
) -> tuple[SAC, list[float]]:
    env = env_factory()
    model = SAC("MlpPolicy", env, seed=seed, verbose=0)
    callback = _RewardCurveCallback()
    model.learn(total_timesteps=total_timesteps, callback=callback)
    return model, callback.episode_rewards


def train_policy(
    algorithm: Literal["PPO", "SAC"],
    env_factory: Callable[[], gym.Env[np.ndarray, np.ndarray]],
    total_timesteps: int,
    seed: int,
) -> tuple[PPO | SAC, list[float]]:
    if algorithm == "PPO":
        return train_ppo(env_factory, total_timesteps, seed)
    return train_sac(env_factory, total_timesteps, seed)
