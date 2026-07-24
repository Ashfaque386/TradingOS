"""Monte Carlo Temporal workflow (Phase 3 Epic E3.3), per Phase_3_Low_Level_Design.md §7:
"Monte Carlo Cluster: Distributes 10,000 randomized backtest runs across ... worker nodes."

Runs on the real, single-node `temporal` docker-compose service rather than a distributed
Kubernetes worker pool (Phase 3 decision -- a single node is sufficient at this scale). The
10,000-path simulation is still split into batches and distributed as concurrent Temporal
activities, so the same workflow definition scales to a multi-worker pool later without any
code change, just more workers registered against the same task queue.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta

import numpy as np
from temporalio import activity, workflow
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

from src.engine.optimization.monte_carlo import DRAWDOWN_PERCENTILE, max_drawdown_from_returns

DEFAULT_N_BATCHES = 10

# numpy's C-extension init state can't be re-imported inside Temporal's per-workflow sandbox
# ("cannot load module more than once per process"); passthrough gives the sandbox the
# already-imported real module instead of re-executing it in isolation. Safe here because
# MonteCarloWorkflow only uses numpy for a single, non-random aggregation (percentile of
# activity-returned floats) -- all the actual randomness lives in the activity, which isn't
# sandboxed at all. Any Worker registering this workflow must pass `workflow_runner=
# MONTE_CARLO_WORKFLOW_RUNNER` (see src/workers/monte_carlo_worker.py).
MONTE_CARLO_WORKFLOW_RUNNER = SandboxedWorkflowRunner(
    restrictions=SandboxRestrictions.default.with_passthrough_modules("numpy")
)


@dataclass
class MonteCarloBatchInput:
    trade_returns: list[float]
    n_simulations: int
    seed: int


@activity.defn
async def run_monte_carlo_batch(input: MonteCarloBatchInput) -> list[float]:
    """One batch of resampled-path Max Drawdown simulations -- a pure CPU-bound numpy
    computation, safe to run synchronously inside the activity."""
    returns = np.asarray(input.trade_returns, dtype=float)
    rng = np.random.default_rng(input.seed)
    results = np.empty(input.n_simulations)
    for i in range(input.n_simulations):
        resampled = rng.choice(returns, size=len(returns), replace=True)
        results[i] = max_drawdown_from_returns(resampled)
    return results.tolist()


@dataclass
class MonteCarloWorkflowInput:
    trade_returns: list[float]
    n_simulations: int = 10_000
    n_batches: int = DEFAULT_N_BATCHES


@dataclass
class MonteCarloWorkflowResult:
    n_simulations: int
    historical_max_drawdown: float
    percentile_95_max_drawdown: float
    simulated_max_drawdowns: list[float] = field(default_factory=list)


def _split_into_batches(total: int, n_batches: int) -> list[int]:
    """Splits `total` simulations into `n_batches` near-equal integer batch sizes (the
    remainder is spread across the first few batches rather than dropped)."""
    base, remainder = divmod(total, n_batches)
    return [base + (1 if i < remainder else 0) for i in range(n_batches)]


@workflow.defn
class MonteCarloWorkflow:
    @workflow.run
    async def run(self, input: MonteCarloWorkflowInput) -> MonteCarloWorkflowResult:
        batch_sizes = [
            size for size in _split_into_batches(input.n_simulations, input.n_batches) if size > 0
        ]

        batch_results = await asyncio.gather(
            *[
                workflow.execute_activity(
                    run_monte_carlo_batch,
                    MonteCarloBatchInput(
                        trade_returns=input.trade_returns, n_simulations=size, seed=i
                    ),
                    start_to_close_timeout=timedelta(minutes=5),
                )
                for i, size in enumerate(batch_sizes)
            ]
        )

        simulated_max_drawdowns = [dd for batch in batch_results for dd in batch]
        historical_max_drawdown = max_drawdown_from_returns(
            np.asarray(input.trade_returns, dtype=float)
        )
        percentile_95 = float(np.percentile(simulated_max_drawdowns, DRAWDOWN_PERCENTILE))

        return MonteCarloWorkflowResult(
            n_simulations=len(simulated_max_drawdowns),
            historical_max_drawdown=historical_max_drawdown,
            percentile_95_max_drawdown=percentile_95,
            simulated_max_drawdowns=simulated_max_drawdowns,
        )
