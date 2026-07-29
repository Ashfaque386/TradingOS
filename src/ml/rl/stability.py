"""REL-008 E8.4: seed-stability rejection (AGT-018's own design-doc error-handling rule: "If
reward curve variance across seeds exceeds a configured stability threshold, reject the run and
flag for reward-function redesign"). Threshold confirmed with the user (AskUserQuestion,
REL-008 planning): 0.5 coefficient of variation.
"""

from dataclasses import dataclass

import numpy as np

REWARD_VARIANCE_CV_THRESHOLD = 0.5


@dataclass
class StabilityResult:
    passed: bool
    mean_final_reward_by_seed: dict[int, float]
    coefficient_of_variation: float


def assess_seed_stability(
    reward_curves: dict[int, list[float]], *, final_n_episodes: int = 5
) -> StabilityResult:
    """`reward_curves` maps seed -> that seed's per-episode reward history. Compares the mean of
    each seed's final `final_n_episodes` episode rewards -- the coefficient of variation (std/
    |mean|) across seeds must not exceed REWARD_VARIANCE_CV_THRESHOLD."""
    if len(reward_curves) < 2:
        raise ValueError("stability assessment needs at least 2 seeds to compare")

    means_by_seed: dict[int, float] = {}
    for seed, curve in reward_curves.items():
        if not curve:
            raise ValueError(f"seed {seed} has an empty reward curve")
        tail = curve[-final_n_episodes:]
        means_by_seed[seed] = float(np.mean(tail))

    means = np.array(list(means_by_seed.values()))
    mean_of_means = float(means.mean())
    std_of_means = float(means.std())
    cv = std_of_means / abs(mean_of_means) if mean_of_means != 0 else float("inf")

    return StabilityResult(
        passed=cv <= REWARD_VARIANCE_CV_THRESHOLD,
        mean_final_reward_by_seed=means_by_seed,
        coefficient_of_variation=cv,
    )
