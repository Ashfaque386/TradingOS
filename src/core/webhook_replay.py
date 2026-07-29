"""Webhook replay-attack prevention (REL-007 E7.7, SEC-029): a captured-and-replayed inbound
webhook request must not re-trigger whatever action it caused the first time. Real Redis, not an
in-process cache -- this must survive across app restarts/multiple workers for the guarantee to
mean anything.
"""

import redis

_REPLAY_KEY_PREFIX = "webhook:seen"
_REPLAY_TTL_SECONDS = 24 * 60 * 60  # SEC-029's specified 24h window


def is_replay(channel: str, message_id: str, *, redis_client: redis.Redis) -> bool:
    """Atomically records `message_id` as seen and reports whether it was already seen --
    `SET ... NX` is a single atomic operation, so two concurrent requests for the same
    (channel, message_id) can never both be told "not a replay" (a check-then-set race would
    allow exactly that). Returns True if this is a replay (the key already existed)."""
    key = f"{_REPLAY_KEY_PREFIX}:{channel}:{message_id}"
    was_set = redis_client.set(key, "1", nx=True, ex=_REPLAY_TTL_SECONDS)
    return not was_set
