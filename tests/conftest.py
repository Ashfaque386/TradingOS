"""Session-wide test fixtures."""

import os

import pytest

# REL-064 (API-014): must run before any test *module* import (conftest.py itself always loads
# before pytest collects/imports test files) -- src.core.config's get_settings() is @lru_cache'd,
# and src.api.main reads it at *module import time* (the zap_test_endpoint_enabled check), so this
# has to land before the first import of anything that transitively imports the app. Real
# automated-test traffic (hundreds of calls across the suite, often sharing one TestClient IP/
# user) is exactly the exceptional pattern RateLimitMiddleware isn't meant to police -- the
# middleware itself still gets dedicated tests with this flag explicitly re-enabled
# (tests/integration/test_rate_limit_middleware.py), so disabling it here doesn't leave the
# feature untested, just unexercised by every unrelated test.
os.environ.setdefault("API_RATE_LIMIT_ENABLED", "false")


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
