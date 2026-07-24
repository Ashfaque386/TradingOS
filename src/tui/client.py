"""Thin async client over TradingOS's real FastAPI REST/WS surface (Phase 4 E4.3 Terminal UI,
Phase_7_Frontend_Architecture.md §2.6). This is a client of the same backend the Next.js
dashboard talks to -- not a second implementation of anything, and not a mock: every method here
hits a real, already-tested endpoint (src/api/routers/{system,portfolio,agents}.py).

Defaults to http://localhost:8000 because the TUI is meant to be run inside the same `app`
container as the FastAPI process it's monitoring (`docker compose exec app python -m
src.tui.app`) -- see Dockerfile / docker-compose.yml, nothing runs outside Docker in this
project. Overridable via TUI_API_BASE_URL for a genuinely separate host.
"""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from typing import Any, cast

import httpx
import websockets

API_BASE_URL = os.environ.get("TUI_API_BASE_URL", "http://localhost:8000")
WS_BASE_URL = API_BASE_URL.replace("http", "ws", 1)


class TUIClient:
    def __init__(self, base_url: str = API_BASE_URL) -> None:
        self._base_url = base_url
        # 5.0s was too tight in practice: the TUI shares its container with the FastAPI
        # process it's monitoring, and a real vectorbt backtest running concurrently
        # (numba JIT, CPU-heavy) can push a simple /health response past 5s -- observed as a
        # flaky "unreachable" false-positive during a full pytest run, not a real outage.
        self._http = httpx.AsyncClient(base_url=base_url, timeout=10.0)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def health(self) -> dict[str, Any]:
        response = await self._http.get("/health")
        response.raise_for_status()
        return cast(dict[str, Any], response.json())

    async def kill_switch_status(self) -> dict[str, Any]:
        response = await self._http.get("/api/v1/system/kill-switch/status")
        response.raise_for_status()
        return cast(dict[str, Any], response.json())

    async def risk_metrics(self) -> dict[str, Any]:
        response = await self._http.get("/api/v1/portfolio/risk-metrics")
        response.raise_for_status()
        return cast(dict[str, Any], response.json())

    async def recent_runs(self) -> list[dict[str, Any]]:
        response = await self._http.get("/api/v1/agents/runs")
        response.raise_for_status()
        return list(response.json())

    async def stream_agent_logs(self) -> AsyncIterator[dict[str, Any]]:
        """Connects to the real /stream/agents/logs relay (src/api/routers/streams.py) and
        yields each decoded log payload as it arrives -- reconnects on any disconnect rather
        than dying, since a dev backend restart (common in this environment, see
        src/api/routers/agents.py's threading notes) shouldn't take the TUI down with it."""
        url = f"{self._base_url.replace('http', 'ws', 1)}/api/v1/stream/agents/logs"
        while True:
            try:
                async with websockets.connect(url) as ws:
                    async for raw in ws:
                        try:
                            yield json.loads(raw)
                        except json.JSONDecodeError:
                            continue
            except (OSError, websockets.exceptions.WebSocketException):
                yield {
                    "agent_id": "tui",
                    "node": "connection",
                    "message": "disconnected, retrying…",
                    "ts": "",
                }
                await asyncio.sleep(3)
