"""Optimization Agent node integration test (REL-005 E5.3 exit criterion): a real Monte Carlo
Temporal workflow call against the real `temporal` docker-compose service.

Runs the node's actual synchronous `asyncio.run(...)` call path (as it runs in production, e.g.
from `_execute_graph_run`'s background thread), while an in-process `Worker` -- started in its
own background thread/event loop, mirroring how the real standing `monte-carlo-worker`
docker-compose service is a wholly separate OS process from the app -- consumes the real
`settings.temporal_task_queue`. Proves the node's `execute_workflow` call shape resolves for
real, independent of whether the standing compose worker also happens to be running.
"""

import asyncio
import threading

from temporalio.client import Client
from temporalio.worker import Worker

from src.agents.nodes.optimization import optimization_node
from src.agents.state import EquityCurvePoint, EvaluationVerdict, TradingOSGraphState
from src.core.config import get_settings
from src.workers.monte_carlo_workflow import (
    MONTE_CARLO_WORKFLOW_RUNNER,
    MonteCarloWorkflow,
    run_monte_carlo_batch,
)


class _BackgroundWorker:
    """Runs a real in-process Temporal Worker on the real shared task queue for the duration of
    a `with` block, in its own thread/event loop -- a sync test can't `await` a Worker directly,
    and the node under test calls `asyncio.run()` itself, so no event loop can already be running
    on the test's own thread when `optimization_node` is invoked."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "_BackgroundWorker":
        ready = threading.Event()

        def _run() -> None:
            asyncio.run(self._serve(ready))

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        ready.wait(timeout=10)
        return self

    async def _serve(self, ready: threading.Event) -> None:
        settings = get_settings()
        client = await Client.connect(settings.temporal_address)
        async with Worker(
            client,
            task_queue=settings.temporal_task_queue,
            workflows=[MonteCarloWorkflow],
            activities=[run_monte_carlo_batch],
            workflow_runner=MONTE_CARLO_WORKFLOW_RUNNER,
        ):
            ready.set()
            while not self._stop.is_set():
                await asyncio.sleep(0.1)

    def __exit__(self, *exc_info: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)


def test_optimization_node_runs_real_monte_carlo_via_temporal() -> None:
    equity_curve = [
        EquityCurvePoint(date=f"2024-01-{day:02d}", equity=equity)
        for day, equity in enumerate(
            [100_000, 101_000, 99_500, 102_000, 98_000, 103_000, 97_000, 104_000, 96_000, 105_000],
            start=1,
        )
    ]
    state = TradingOSGraphState(
        thread_id="opt-integration-test",
        equity_curve=equity_curve,
        evaluation_verdict=EvaluationVerdict(verdict="PASS"),
    )

    with _BackgroundWorker():
        result = optimization_node(state)

    opt = result["optimization_result"]
    assert opt.robustness_score is not None
    assert opt.robustness_score >= 0.0
    assert "Walk-Forward" in opt.notes
