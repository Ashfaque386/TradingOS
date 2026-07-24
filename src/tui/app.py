"""TradingOS Terminal UI (Phase 4 Epic E4.3), backing Phase_7_Frontend_Architecture.md §2.6's
"Developer Dashboard: a premium, fast command-line interface for quant developers to monitor
agent execution natively in the terminal, featuring live log streams and system health metrics
without requiring a web browser."

Every panel here is real data from the same backend the Next.js dashboard uses (see
src/tui/client.py) -- the kill-switch state, risk metrics, and recent-run list are polled REST
calls; the Thought Stream is the real /stream/agents/logs WebSocket relay. Nothing here is a
second implementation of anything or a mock -- this is deliberately just another real client.

Run inside the same container as the FastAPI process (`docker compose exec app python -m
src.tui.app`), matching this project's Docker-only development rule.
"""

import contextlib
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, RichLog, Static

from src.tui.client import TUIClient

POLL_INTERVAL_SECONDS = 5.0


class SystemHealthPanel(Static):
    """Kill-switch state + daily risk snapshot, per §2.6's "system health metrics." Shows an
    honest "—" for anything not yet available (e.g. no risk limit configured) rather than a
    fabricated number, same convention as the web dashboard's Portfolio & Risk module."""

    kill_switch_state: reactive[str] = reactive("—")
    tripped_at: reactive[str | None] = reactive(None)
    daily_pnl: reactive[float | None] = reactive(None)
    pct_of_limit: reactive[float | None] = reactive(None)
    backend_reachable: reactive[bool] = reactive(False)

    def render(self) -> str:
        health = "[green]● reachable[/]" if self.backend_reachable else "[red]● unreachable[/]"
        state_color = "red" if self.kill_switch_state == "TRIPPED" else "green"
        pnl_str = f"₹{self.daily_pnl:,.0f}" if self.daily_pnl is not None else "—"
        pct_str = f"{self.pct_of_limit:.0f}%" if self.pct_of_limit is not None else "—"

        lines = [
            "[b]SYSTEM HEALTH[/b]",
            f"Backend:      {health}",
            f"Kill Switch:  [{state_color}]{self.kill_switch_state}[/]",
        ]
        if self.tripped_at:
            lines.append(f"  tripped at: {self.tripped_at}")
        lines += [
            f"Daily P&L:    {pnl_str}",
            f"Of daily limit: {pct_str}",
        ]
        return "\n".join(lines)


class RecentRunsPanel(Static):
    runs: reactive[list[dict[str, str]]] = reactive(list)

    def render(self) -> str:
        if not self.runs:
            return "[b]RECENT AGENT RUNS[/b]\n[dim]No runs yet.[/dim]"
        lines = ["[b]RECENT AGENT RUNS[/b]"]
        for run in self.runs[:8]:
            color = {"Running": "cyan", "Completed": "green", "Failed": "red"}.get(
                run["status"], "white"
            )
            started = run["started_at"][11:19] if len(run["started_at"]) > 19 else run["started_at"]
            lines.append(f"[{color}]{run['status']:<10}[/] {started}  {run['thread_id'][:8]}")
        return "\n".join(lines)


class TradingOSTUI(App[None]):
    CSS = """
    Screen {
        background: #09090b;
    }
    #left-column {
        width: 38;
        border: round #27272a;
        padding: 1;
    }
    #health-panel {
        height: auto;
        border-bottom: solid #27272a;
        padding-bottom: 1;
        margin-bottom: 1;
    }
    #log-panel {
        border: round #27272a;
        padding: 0 1;
    }
    RichLog {
        background: #09090b;
    }
    """

    BINDINGS = [("q", "quit", "Quit"), ("r", "refresh_now", "Refresh")]

    def __init__(self) -> None:
        super().__init__()
        self.client = TUIClient()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="left-column"):
                yield SystemHealthPanel(id="health-panel")
                yield RecentRunsPanel(id="runs-panel")
            yield RichLog(id="log-panel", highlight=True, markup=True, wrap=True)
        yield Footer()

    async def on_mount(self) -> None:
        self.title = "TradingOS"
        self.sub_title = "Agent Console — Terminal"
        log = self.query_one("#log-panel", RichLog)
        log.write("[dim]Connecting to the agent log stream…[/dim]")

        self.set_interval(POLL_INTERVAL_SECONDS, self.poll_health)
        await self.poll_health()
        self.run_worker(self.consume_agent_logs(), exclusive=True)

    async def poll_health(self) -> None:
        panel = self.query_one("#health-panel", SystemHealthPanel)
        runs_panel = self.query_one("#runs-panel", RecentRunsPanel)

        try:
            await self.client.health()
            panel.backend_reachable = True
        except Exception:  # noqa: BLE001 - a health-check failure is real, honest "unreachable"
            panel.backend_reachable = False
            return

        try:
            status = await self.client.kill_switch_status()
            panel.kill_switch_state = status["state"]
            panel.tripped_at = status["tripped_at"]
        except Exception:  # noqa: BLE001
            panel.kill_switch_state = "—"

        try:
            risk = await self.client.risk_metrics()
            panel.daily_pnl = risk["daily_pnl"]
            panel.pct_of_limit = risk["pct_of_daily_limit_used"]
        except Exception:  # noqa: BLE001
            panel.daily_pnl = None
            panel.pct_of_limit = None

        with contextlib.suppress(Exception):  # noqa: BLE001
            runs_panel.runs = await self.client.recent_runs()

    async def consume_agent_logs(self) -> None:
        log = self.query_one("#log-panel", RichLog)
        async for entry in self.client.stream_agent_logs():
            ts = entry.get("ts") or datetime.now().strftime("%H:%M:%S")
            ts_short = ts[11:19] if len(ts) > 19 else ts
            node = entry.get("node", "?")
            message = entry.get("message", "")
            log.write(f"[dim]{ts_short}[/dim] [b magenta]\\[{node}][/] {message}")

    async def action_refresh_now(self) -> None:
        await self.poll_health()

    async def on_unmount(self) -> None:
        await self.client.aclose()


if __name__ == "__main__":
    TradingOSTUI().run()
