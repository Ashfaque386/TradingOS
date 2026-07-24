"""Redis connection + pub/sub scaffold for live tick distribution (Phase 3/4, per LLD §7)."""

from collections.abc import Callable

import redis

from src.core.config import get_settings

TICK_CHANNEL_PREFIX = "ticks:"

# Agent thought-process/tool-call stream (Phase 4 E4.2, API-092 in Phase_10_API_Design.md §16:
# "/stream/agents/logs" -- "Real-time AI agent thought process & tool-call stream for the
# dashboard"). A single shared channel, not one per agent: the dashboard subscribes to the
# whole stream and filters client-side by `agent_id`, matching how API-092 is specified.
AGENT_LOG_CHANNEL = "agent-logs"


def get_redis_client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def publish_tick(client: redis.Redis, symbol: str, payload: str) -> int:
    return client.publish(f"{TICK_CHANNEL_PREFIX}{symbol}", payload)


def publish_agent_log(client: redis.Redis, payload: str) -> int:
    return client.publish(AGENT_LOG_CHANNEL, payload)


def subscribe_ticks(client: redis.Redis, symbol: str, on_message: Callable[[str], None]) -> None:
    # redis-py's PubSub methods are untyped in its stubs; the object itself is fully typed.
    pubsub: redis.client.PubSub = client.pubsub()  # type: ignore[no-untyped-call]
    pubsub.subscribe(f"{TICK_CHANNEL_PREFIX}{symbol}")
    for message in pubsub.listen():  # type: ignore[no-untyped-call]
        if message["type"] == "message":
            on_message(message["data"])
