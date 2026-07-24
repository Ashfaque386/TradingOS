"""Temporal worker process for the Monte Carlo workflow (Phase 3 Epic E3.3). Run via
`docker compose run --rm app python -m src.workers.monte_carlo_worker` once the `temporal`
docker-compose service is up -- registers `MonteCarloWorkflow` + `run_monte_carlo_batch` on
the configured task queue and blocks, processing workflow executions until stopped.
"""

import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from src.core.config import get_settings
from src.workers.monte_carlo_workflow import (
    MONTE_CARLO_WORKFLOW_RUNNER,
    MonteCarloWorkflow,
    run_monte_carlo_batch,
)


async def main() -> None:
    settings = get_settings()
    client = await Client.connect(settings.temporal_address)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[MonteCarloWorkflow],
        activities=[run_monte_carlo_batch],
        workflow_runner=MONTE_CARLO_WORKFLOW_RUNNER,
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
