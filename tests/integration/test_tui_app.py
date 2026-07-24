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

import pytest

from src.tui.app import RecentRunsPanel, SystemHealthPanel, TradingOSTUI


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
