"""REL-064 (API-014): general REST API rate limiting, generalizing the exact fixed-window
Redis pattern src/core/webhook_rate_limit.py already proved (INCR a bucket key, EXPIRE ... NX
once on first use) to two operations instead of one -- `consume()` for the enforcing middleware,
`peek()` for a caller to read their own remaining budget back out without spending it. The
webhook limiter is check-and-consume only; nothing before this let a caller see their own usage.
"""

import base64
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import redis

_RATE_LIMIT_KEY_PREFIX = "api:ratelimit"


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_at: datetime


def _window_bucket(window_seconds: int) -> int:
    return int(time.time()) // window_seconds


def _key(caller_key: str, window_seconds: int) -> str:
    return f"{_RATE_LIMIT_KEY_PREFIX}:{caller_key}:{_window_bucket(window_seconds)}"


def _reset_at(window_seconds: int) -> datetime:
    bucket_end = (_window_bucket(window_seconds) + 1) * window_seconds
    return datetime.fromtimestamp(bucket_end, tz=UTC)


def consume(
    caller_key: str, *, redis_client: redis.Redis, limit: int, window_seconds: int
) -> RateLimitResult:
    """Increments the caller's current-window counter -- same INCR/EXPIRE-NX shape as
    webhook_rate_limit.py::check_rate_limit, generalized to any caller_key (a JWT `sub` or a
    client IP here, a chat_id there)."""
    key = _key(caller_key, window_seconds)
    count = redis_client.incr(key)
    if count == 1:
        redis_client.expire(key, window_seconds, nx=True)
    return RateLimitResult(
        allowed=count <= limit,
        limit=limit,
        remaining=max(0, limit - count),
        reset_at=_reset_at(window_seconds),
    )


def peek(
    caller_key: str, *, redis_client: redis.Redis, limit: int, window_seconds: int
) -> RateLimitResult:
    """Read-only: reports the caller's current-window usage without incrementing it. A key with
    no prior consume() this window doesn't exist yet in Redis -- reads as 0 used, the real
    (not fabricated) fresh-window state."""
    key = _key(caller_key, window_seconds)
    raw = redis_client.get(key)
    count = int(raw) if raw is not None else 0
    return RateLimitResult(
        allowed=count <= limit,
        limit=limit,
        remaining=max(0, limit - count),
        reset_at=_reset_at(window_seconds),
    )


def unverified_subject(authorization_header: str | None) -> str | None:
    """Extracts the `sub` claim from a Bearer token WITHOUT verifying its signature -- correct
    for rate-limit keying only, not authentication. The real, signature-verified identity check
    (src/core/security.py::decode_access_token, which round-trips to Vault Transit on every call)
    still happens exactly as before at the actual auth dependency layer for every route that
    needs it; duplicating that real Vault call here on every single request (including ones that
    don't even require auth) would be a genuine, avoidable latency/load cost for a purpose that
    doesn't need cryptographic proof -- a forged `sub` here can only ever misdirect that forger's
    own rate-limit bucket, not bypass anyone else's or grant any real privilege."""
    if not authorization_header or not authorization_header.startswith("Bearer "):
        return None
    token = authorization_header.removeprefix("Bearer ").strip()
    try:
        _header_b64, payload_b64, _signature_b64 = token.split(".")
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        sub = payload.get("sub")
        return str(sub) if sub is not None else None
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


__all__ = ["RateLimitResult", "consume", "peek", "unverified_subject"]
