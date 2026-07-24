"""Async Redis tick listener (Phase 4 Epic E4.2) feeding `LiveExecutionPipeline.handle_tick()`.

Uses `redis.asyncio` (redis-py's async client) rather than src/memory/redis_client.py's
synchronous pub/sub scaffold -- this pipeline's <50ms tick-to-order latency budget (NFR-02)
needs non-blocking I/O throughout, including the Redis read itself, not just the broker HTTP
call. Shares `TICK_CHANNEL_PREFIX` with src/memory/redis_client.py so both paths agree on
channel names (`ticks:<symbol>`).
"""

import json
from datetime import UTC, datetime

import redis.asyncio as aioredis

from src.core.config import get_settings
from src.engine.live.execution_pipeline import LiveExecutionPipeline, Tick
from src.memory.redis_client import TICK_CHANNEL_PREFIX


def get_async_redis_client() -> aioredis.Redis:
    return aioredis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def parse_tick_payload(symbol: str, raw: str) -> Tick:
    """Tick payloads are JSON: `{"price": <float>, "timestamp": "<ISO 8601>"}`. A missing
    timestamp defaults to "now" rather than failing the whole tick -- a late or malformed
    timestamp shouldn't drop real market data."""
    data = json.loads(raw)
    timestamp_str = data.get("timestamp")
    timestamp = datetime.fromisoformat(timestamp_str) if timestamp_str else datetime.now(UTC)
    return Tick(symbol=symbol, price=float(data["price"]), timestamp=timestamp)


async def run_tick_listener(
    client: aioredis.Redis,
    pipeline: LiveExecutionPipeline,
    *,
    pattern: str = f"{TICK_CHANNEL_PREFIX}*",
) -> None:
    """Subscribes to every tick channel matching `pattern` and feeds each message through
    `pipeline.handle_tick()`. Runs until cancelled -- callers manage the task lifecycle (e.g. an
    `asyncio.Task` started at FastAPI startup, cancelled at shutdown)."""
    pubsub = client.pubsub()
    await pubsub.psubscribe(pattern)
    try:
        async for message in pubsub.listen():
            if message["type"] != "pmessage":
                continue
            channel: str = message["channel"]
            symbol = channel.removeprefix(TICK_CHANNEL_PREFIX)
            tick = parse_tick_payload(symbol, message["data"])
            await pipeline.handle_tick(tick)
    finally:
        await pubsub.punsubscribe(pattern)
        await pubsub.aclose()  # type: ignore[no-untyped-call]  # redis-py's async PubSub is untyped here
