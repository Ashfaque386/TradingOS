"""Session-wide test fixtures."""

import pytest


@pytest.fixture(scope="session", autouse=True)
def _shutdown_sandbox_pool_after_session():
    """REL-032: src/engine/sandbox/pool.py's warm worker pool is a process-wide singleton --
    once any test exercises the real-backtest path (execute_in_pool), its warm worker
    subprocess(es) stay resident for the rest of this pytest session, by design (matching the
    real FastAPI app's own long-running-process lifecycle, where staying warm is the entire
    point). For the test suite specifically that's real, non-trivial memory (~400MB+ per
    worker, measured) held for however much of the run remains after the first real-backtest
    test -- shutting it down here bounds that to test-hygiene, not a change to production
    behavior."""
    yield
    from src.engine.sandbox.pool import shutdown_pool

    shutdown_pool()
