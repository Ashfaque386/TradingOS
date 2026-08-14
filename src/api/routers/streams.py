"""Live streaming WebSocket endpoints (Phase 4 Epic E4.2), per Phase_10_API_Design.md §16:

  API-091 WS `/stream/market/{symbol}` -- live tick data from Redis pub/sub,
    `{symbol, ltp, volume, ts}` per tick.
  API-092 WS `/stream/agents/logs` -- AI agent thought-process/tool-call stream,
    `{agent_id, node, message, ts}`.
  API-094 WS `/stream/portfolio` -- live portfolio PnL/margin ticker, `{pnl, drawdown,
    margin_used, ts}`, polled from the live broker adapter every 3s (there is no
    pub/sub channel for portfolio state -- unlike ticks/agent-logs, nothing publishes it, so
    this endpoint polls the same broker.get_positions()/get_margin() calls
    src/api/routers/portfolio.py uses, rather than relaying an existing feed).
  API-093 WS `/stream/orders` -- live order status updates (placed/filled/cancelled),
    published by src/api/routers/orders.py's place_order()/cancel_order() (REL-061) at the one
    and only place Order/PaperTrade rows are ever created or transitioned in this codebase.

Both endpoints are thin relays: subscribe to the relevant Redis pub/sub channel(s) and forward
each message to the connected WebSocket client as JSON, reshaping tick payloads to the exact
field names Phase_10_API_Design.md specifies (agent-log payloads are already in that shape at
the publisher, src/memory/redis_client.py's `publish_agent_log()`, so those are relayed
verbatim). Auth/RBAC (Any / PM,RM,SA,Auditor per the API doc) is not enforced here -- same
documented gap as src/api/routers/system.py: no JWT/auth module exists yet anywhere in the
codebase.

Any error while relaying (client disconnect, Redis hiccup) simply ends the relay loop -- this is
a read-only display feed, not an order-routing path, so there is nothing risk-sensitive to
protect by treating errors more strictly here.
"""

import asyncio
import json
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket

from src.api.routers.portfolio import _latest_risk_limit, _pct_of_daily_limit
from src.brokers.factory import NoBrokerConfigured, build_broker
from src.core.db import get_session
from src.engine.live.tick_listener import get_async_redis_client
from src.engine.risk.ws_latency_guard_service import get_latency_guard
from src.memory.redis_client import AGENT_LOG_CHANNEL, ORDER_EVENT_CHANNEL, TICK_CHANNEL_PREFIX
from src.observability.metrics import WS_STREAM_LATENCY_SECONDS

_PORTFOLIO_POLL_INTERVAL_SECONDS = 3.0

router = APIRouter(prefix="/api/v1/stream", tags=["stream"])


@router.websocket("/market/{symbol}")
async def stream_market_ticks(websocket: WebSocket, symbol: str) -> None:
    """API-091. Also measures relay latency (tick timestamp -> about to send) for the
    Prometheus WS-latency alert / auto-pause (Phase_9_Master_Implementation_Guide.md §5 Risk
    Register) -- skipped when a tick has no timestamp, since latency can't be measured against
    nothing."""
    await websocket.accept()
    client = get_async_redis_client()
    pubsub = client.pubsub()
    channel = f"{TICK_CHANNEL_PREFIX}{symbol}"
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            tick = json.loads(message["data"])

            timestamp_str = tick.get("timestamp")
            if timestamp_str:
                tick_time = datetime.fromisoformat(timestamp_str)
                latency = (datetime.now(UTC) - tick_time).total_seconds()
                WS_STREAM_LATENCY_SECONDS.labels(stream="market").observe(latency)
                get_latency_guard().record(latency)

            await websocket.send_json(
                {
                    "symbol": symbol,
                    "ltp": tick["price"],
                    "volume": tick.get("volume", 0),
                    "ts": timestamp_str,
                }
            )
    except Exception:
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()  # type: ignore[no-untyped-call]
        await client.aclose()


@router.websocket("/agents/logs")
async def stream_agent_logs(websocket: WebSocket) -> None:
    """API-092."""
    await websocket.accept()
    client = get_async_redis_client()
    pubsub = client.pubsub()
    await pubsub.subscribe(AGENT_LOG_CHANNEL)
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            await websocket.send_text(message["data"])
    except Exception:
        pass
    finally:
        await pubsub.unsubscribe(AGENT_LOG_CHANNEL)
        await pubsub.aclose()  # type: ignore[no-untyped-call]
        await client.aclose()


@router.websocket("/orders")
async def stream_order_events(websocket: WebSocket) -> None:
    """API-093 (REL-061). Same thin verbatim-relay shape as /agents/logs above."""
    await websocket.accept()
    client = get_async_redis_client()
    pubsub = client.pubsub()
    await pubsub.subscribe(ORDER_EVENT_CHANNEL)
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            await websocket.send_text(message["data"])
    except Exception:
        pass
    finally:
        await pubsub.unsubscribe(ORDER_EVENT_CHANNEL)
        await pubsub.aclose()  # type: ignore[no-untyped-call]
        await client.aclose()


@router.websocket("/portfolio")
async def stream_portfolio(websocket: WebSocket) -> None:
    """API-094. Polling, not pub/sub relay -- see module docstring. `drawdown` is the same
    pct-of-daily-loss-limit figure src/api/routers/portfolio.py's /portfolio/pnl exposes (real,
    limit-relative), not a peak-equity drawdown -- nothing tracks a live equity high-water mark
    yet."""
    await websocket.accept()
    try:
        broker = build_broker()
    except NoBrokerConfigured as exc:
        await websocket.close(code=1011, reason=str(exc))
        return

    try:
        while True:
            positions = await broker.get_positions()
            pnl = sum(p.unrealized_pnl + p.realized_pnl for p in positions)
            margin = await broker.get_margin()

            with get_session() as session:
                limit = _latest_risk_limit(session)
                daily_limit = float(limit.max_daily_loss) if limit else None

            await websocket.send_json(
                {
                    "pnl": pnl,
                    "drawdown": _pct_of_daily_limit(pnl, daily_limit),
                    "margin_used": margin.used_margin,
                    "ts": datetime.now(UTC).isoformat(),
                }
            )
            await asyncio.sleep(_PORTFOLIO_POLL_INTERVAL_SECONDS)
    except Exception:
        pass
