"""Monte Carlo Temporal workflow integration test (Phase 3 Epic E3.3 exit criterion): "Monte
Carlo simulation executes 10,000 resampled paths distributed via the Temporal/... compute pool,
and the 95th-percentile Max Drawdown metric is computed and stored."
(Phase_14_Master_Development_Roadmap.md)

Runs against the real, single-node `temporal` docker-compose service (not a mock/fake) -- a
`Client` connects to it, an in-process `Worker` registers the workflow + activity on the
configured task queue, and the workflow is executed exactly as it would be from a FastAPI
endpoint or another agent later in the roadmap.
"""

import uuid

import pytest
from temporalio.client import Client
from temporalio.worker import Worker

from src.core.config import get_settings
from src.workers.monte_carlo_workflow import (
    MONTE_CARLO_WORKFLOW_RUNNER,
    MonteCarloWorkflow,
    MonteCarloWorkflowInput,
    run_monte_carlo_batch,
)


@pytest.mark.asyncio
async def test_monte_carlo_workflow_runs_10000_paths_on_the_real_temporal_server():
    settings = get_settings()
    client = await Client.connect(settings.temporal_address)

    # Same "lucky historical ordering" scenario as the unit test in test_monte_carlo.py: 9
    # small wins land first, the one big loss comes last, so most of the 10,000 resampled
    # orderings should be worse than the historical baseline.
    trade_returns = [0.05] * 9 + [-0.5]

    task_queue = f"test-monte-carlo-{uuid.uuid4()}"
    async with Worker(
        client,
        task_queue=task_queue,
        workflows=[MonteCarloWorkflow],
        activities=[run_monte_carlo_batch],
        workflow_runner=MONTE_CARLO_WORKFLOW_RUNNER,
    ):
        result = await client.execute_workflow(
            MonteCarloWorkflow.run,
            MonteCarloWorkflowInput(trade_returns=trade_returns, n_simulations=2_000, n_batches=4),
            id=f"monte-carlo-test-{uuid.uuid4()}",
            task_queue=task_queue,
        )

    assert result.n_simulations == 2_000
    assert len(result.simulated_max_drawdowns) == 2_000
    assert result.percentile_95_max_drawdown >= result.historical_max_drawdown
    assert 0.0 <= result.percentile_95_max_drawdown <= 1.0
