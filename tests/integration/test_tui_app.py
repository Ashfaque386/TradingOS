"""Terminal UI integration test (Phase 4 Epic E4.3, Phase_7_Frontend_Architecture.md §2.6).

Uses Textual's own headless test harness (`App.run_test()`) to actually run the app's event
loop, workers, and timers against the real running FastAPI backend (src/tui/client.py's default
base URL, http://localhost:8000) -- no mocked client, no canned data. This is the terminal
equivalent of the Claude_Browser-driven verification used for every web dashboard module: it
can't take a visual screenshot of a TTY, but it can drive the real widget tree and assert on
real rendered content.

The live WebSocket log stream (src/tui/client.py's `stream_agent_logs`) isn't asserted on here:
whether any agent activity happens to be in flight when this test runs is not deterministic, so
this only checks that the app boots and consumes the stream without crashing (see
test_log_panel_worker_does_not_crash_the_app), not that a specific line appears.
"""

import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import uvicorn

from src.api.main import app as fastapi_app
from src.tui.app import RecentRunsPanel, SystemHealthPanel, TradingOSTUI

_HEALTH_URL = "http://127.0.0.1:8000/health"


@pytest.fixture(scope="module", autouse=True)
def _real_backend_on_localhost_8000() -> Iterator[None]:
    """TUIClient (src/tui/client.py) makes real httpx/websockets socket connections, not
    TestClient's in-process ASGI transport that every other "real backend" integration test in
    this suite uses instead -- it needs an actual listening socket on localhost:8000.

    When this suite runs via `docker compose exec app pytest ...` against the already-running
    `app` service, that container's own uvicorn is already listening there and this is a no-op.
    But CI's `docker compose run --rm app pytest ...` (.github/workflows/ci.yml) starts a fresh,
    isolated one-off container with pytest as its own entrypoint -- the real `app` service is
    never started as a sibling in that job, so nothing is listening on :8000 there. This starts
    a real uvicorn serving the real FastAPI app (same routers, same DB, no mocking) to cover
    that case too.

    lifespan="off": route handlers here don't depend on FastAPI's lifespan (same as every bare
    TestClient(app) integration test elsewhere in this suite, which never enters it either --
    the DB engine and routers are all created at import time, not in the lifespan hook). Skipping
    it also avoids double-starting the real APScheduler daily research cycle that the actual
    `app` container already runs, which would otherwise fire a second, duplicate copy against
    the same Postgres/Redis.
    """
    try:
        httpx.get(_HEALTH_URL, timeout=0.5).raise_for_status()
        yield
        return
    except httpx.HTTPError:
        pass  # nothing listening yet -- start a real one below

    config = uvicorn.Config(
        fastapi_app, host="127.0.0.1", port=8000, log_level="warning", lifespan="off"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 10
    while True:
        try:
            httpx.get(_HEALTH_URL, timeout=0.5).raise_for_status()
            break
        except httpx.HTTPError as exc:
            if time.monotonic() > deadline:
                raise RuntimeError("real backend did not start listening on :8000 in time") from exc
            time.sleep(0.1)

    yield

    server.should_exit = True
    thread.join(timeout=10)


@pytest.mark.asyncio
async def test_app_boots_and_polls_real_backend_health() -> None:
    app = TradingOSTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        # on_mount's poll_health() call should have completed against the real backend by now.
        health_panel = app.query_one("#health-panel", SystemHealthPanel)
        assert health_panel.backend_reachable is True
        assert health_panel.kill_switch_state in {"ARMED", "TRIPPED"}


@pytest.mark.asyncio
async def test_recent_runs_panel_reflects_real_agent_runs() -> None:
    app = TradingOSTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        runs_panel = app.query_one("#runs-panel", RecentRunsPanel)
        # Real data either way: some runs exist from earlier in this session, or none do -- both
        # are valid, this just checks the panel actually reflects whichever is true rather than
        # staying stuck on its pre-mount default.
        rendered = runs_panel.render()
        assert "RECENT AGENT RUNS" in rendered
        if runs_panel.runs:
            assert runs_panel.runs[0]["thread_id"][:8] in rendered


@pytest.mark.asyncio
async def test_log_panel_worker_does_not_crash_the_app() -> None:
    app = TradingOSTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        # The WS worker (consume_agent_logs) is running as a background task; give it a moment
        # to at least attempt a real connection to /stream/agents/logs.
        await pilot.pause(0.5)
        assert app.is_running
