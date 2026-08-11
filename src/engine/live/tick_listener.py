"""Async Redis tick listener (Phase 4 Epic E4.2) feeding `LiveExecutionPipeline.handle_tick()`.

Uses `redis.asyncio` (redis-py's async client) rather than src/memory/redis_client.py's
synchronous pub/sub scaffold -- this pipeline's <50ms tick-to-order latency budget (NFR-02)
needs non-blocking I/O throughout, including the Redis read itself, not just the broker HTTP
call. Shares `TICK_CHANNEL_PREFIX` with src/memory/redis_client.py so both paths agree on
channel names (`ticks:<symbol>`).
"""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol

import redis.asyncio as aioredis

from src.core.config import get_settings
from src.engine.live.execution_pipeline import LiveExecutionPipeline, Tick
from src.memory.redis_client import TICK_CHANNEL_PREFIX


class _TickHandler(Protocol):
    """Structural type for anything with `LiveExecutionPipeline.handle_tick`'s own shape (async,
    takes a `Tick`, returns whatever) -- lets `run_multi_symbol_tick_listener` below stay
    properly typed without `src.engine.live` (a lower-level primitive module) importing
    `PaperExecutionPipeline` from `src.engine.paper_trading` (a higher-level consumer package),
    which would invert that layering even though it wouldn't be a literal circular import."""

    async def handle_tick(self, tick: Tick) -> object: ...


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


async def run_multi_symbol_tick_listener(
    client: aioredis.Redis,
    pipelines_by_symbol: Mapping[str, _TickHandler],
    *,
    pattern: str = f"{TICK_CHANNEL_PREFIX}*",
) -> None:
    """REL-034: the same subscribe/dispatch mechanics as `run_tick_listener` above (`psubscribe`,
    `parse_tick_payload` reused unmodified), but fans a SINGLE Redis subscription out across
    however many pipelines currently need this symbol's ticks, keyed by symbol, instead of one
    subscription per pipeline. `pipelines_by_symbol` is read live on every message (not
    snapshotted at call time) -- src/workers/paper_trading_worker.py mutates a real `dict` it
    passes in here in place as strategies/positions come and go during the day (this function
    only ever reads it, hence the covariant `Mapping` type, which is what actually lets a
    `dict[str, PaperExecutionPipeline]` be passed here at all), so callers never need to restart
    this listener task just to pick up a changed pipeline set."""
    pubsub = client.pubsub()
    await pubsub.psubscribe(pattern)
    try:
        async for message in pubsub.listen():
            if message["type"] != "pmessage":
                continue
            channel: str = message["channel"]
            symbol = channel.removeprefix(TICK_CHANNEL_PREFIX)
            pipeline = pipelines_by_symbol.get(symbol)
            if pipeline is None:
                continue
            tick = parse_tick_payload(symbol, message["data"])
            await pipeline.handle_tick(tick)
    finally:
        await pubsub.punsubscribe(pattern)
        await pubsub.aclose()  # type: ignore[no-untyped-call]  # redis-py's async PubSub is untyped here
