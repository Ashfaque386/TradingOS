"""Per-chat webhook rate limiting (REL-007 E7.7, SEC-031): 10 requests/minute per chat-ID,
preventing a compromised or malicious chat account from flooding the LangGraph orchestrator once
REL-010 wires these primitives up to real message routing.
"""

import time

import redis

_RATE_LIMIT_KEY_PREFIX = "webhook:ratelimit"
DEFAULT_LIMIT = 10
DEFAULT_WINDOW_SECONDS = 60


def check_rate_limit(
    channel: str,
    chat_id: str,
    *,
    redis_client: redis.Redis,
    limit: int = DEFAULT_LIMIT,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> bool:
    """Fixed-window counter keyed by (channel, chat_id, current window bucket). `INCR` on a
    possibly-nonexistent key atomically creates it at 1; `EXPIRE ... NX` (only if the key has no
    TTL yet) sets the window's expiry exactly once, on the first request in that window --
    avoids a read-then-write race where two concurrent first-requests-in-a-window could each
    reset the TTL. Returns True if the request is allowed (under the limit)."""
    window_bucket = int(time.time()) // window_seconds
    key = f"{_RATE_LIMIT_KEY_PREFIX}:{channel}:{chat_id}:{window_bucket}"
    count = redis_client.incr(key)
    if count == 1:
        redis_client.expire(key, window_seconds, nx=True)
    return count <= limit
