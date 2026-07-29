"""src/core/webhook_replay.py + src/core/webhook_rate_limit.py against real Redis (REL-007
E7.7, SEC-029/SEC-031).
"""

import uuid

from src.core.webhook_rate_limit import check_rate_limit
from src.core.webhook_replay import is_replay
from src.memory.redis_client import get_redis_client


def test_a_message_id_is_not_a_replay_the_first_time_but_is_the_second():
    client = get_redis_client()
    message_id = str(uuid.uuid4())
    try:
        assert is_replay("test-channel", message_id, redis_client=client) is False
        assert is_replay("test-channel", message_id, redis_client=client) is True
    finally:
        client.delete(f"webhook:seen:test-channel:{message_id}")


def test_different_channels_do_not_share_a_replay_namespace():
    client = get_redis_client()
    message_id = str(uuid.uuid4())
    try:
        assert is_replay("channel-a", message_id, redis_client=client) is False
        assert is_replay("channel-b", message_id, redis_client=client) is False
    finally:
        client.delete(f"webhook:seen:channel-a:{message_id}")
        client.delete(f"webhook:seen:channel-b:{message_id}")


def test_replay_dedup_key_has_a_real_ttl_set():
    client = get_redis_client()
    message_id = str(uuid.uuid4())
    try:
        is_replay("test-channel", message_id, redis_client=client)
        ttl = client.ttl(f"webhook:seen:test-channel:{message_id}")
        assert 0 < ttl <= 24 * 60 * 60
    finally:
        client.delete(f"webhook:seen:test-channel:{message_id}")


def test_rate_limit_allows_up_to_the_limit_then_blocks():
    client = get_redis_client()
    chat_id = str(uuid.uuid4())
    try:
        results = [
            check_rate_limit("test-channel", chat_id, redis_client=client, limit=3)
            for _ in range(4)
        ]
        assert results == [True, True, True, False]
    finally:
        for key in client.keys(f"webhook:ratelimit:test-channel:{chat_id}:*"):
            client.delete(key)


def test_rate_limit_resets_after_the_window():
    client = get_redis_client()
    chat_id = str(uuid.uuid4())
    try:
        # A 1-second window makes the reset observable without a real 60s sleep.
        assert (
            check_rate_limit(
                "test-channel", chat_id, redis_client=client, limit=1, window_seconds=1
            )
            is True
        )
        assert (
            check_rate_limit(
                "test-channel", chat_id, redis_client=client, limit=1, window_seconds=1
            )
            is False
        )

        import time

        time.sleep(1.1)
        assert (
            check_rate_limit(
                "test-channel", chat_id, redis_client=client, limit=1, window_seconds=1
            )
            is True
        )
    finally:
        for key in client.keys(f"webhook:ratelimit:test-channel:{chat_id}:*"):
            client.delete(key)
