"""src/core/api_rate_limit.py against real Redis (REL-064, API-014) -- consume()/peek()'s
fixed-window behavior, mirroring test_webhook_replay_rate_limit.py's own real-Redis convention.
"""

import time
import uuid

from src.core.api_rate_limit import consume, peek, unverified_subject
from src.memory.redis_client import get_redis_client


def test_consume_allows_up_to_the_limit_then_blocks():
    client = get_redis_client()
    caller = str(uuid.uuid4())
    try:
        results = [
            consume(caller, redis_client=client, limit=3, window_seconds=60) for _ in range(4)
        ]
        assert [r.allowed for r in results] == [True, True, True, False]
        assert [r.remaining for r in results] == [2, 1, 0, 0]
    finally:
        for key in client.keys(f"api:ratelimit:{caller}:*"):
            client.delete(key)


def test_consume_resets_after_the_window():
    client = get_redis_client()
    caller = str(uuid.uuid4())
    try:
        assert consume(caller, redis_client=client, limit=1, window_seconds=1).allowed is True
        assert consume(caller, redis_client=client, limit=1, window_seconds=1).allowed is False
        time.sleep(1.1)
        assert consume(caller, redis_client=client, limit=1, window_seconds=1).allowed is True
    finally:
        for key in client.keys(f"api:ratelimit:{caller}:*"):
            client.delete(key)


def test_peek_never_increments_the_counter():
    client = get_redis_client()
    caller = str(uuid.uuid4())
    try:
        # A fresh caller with no prior consume() reads as real 0-used, not fabricated.
        first = peek(caller, redis_client=client, limit=5, window_seconds=60)
        assert first.remaining == 5

        for _ in range(3):
            consume(caller, redis_client=client, limit=5, window_seconds=60)

        before = peek(caller, redis_client=client, limit=5, window_seconds=60)
        after = peek(caller, redis_client=client, limit=5, window_seconds=60)
        assert before.remaining == 2
        assert after.remaining == 2, "peek() must not itself consume from the budget it reports"
    finally:
        for key in client.keys(f"api:ratelimit:{caller}:*"):
            client.delete(key)


def test_unverified_subject_extracts_sub_from_a_real_token_without_verifying_it():
    from src.core.security import create_access_token

    token = create_access_token(user_id="a-real-user-id", role="SystemAdministrator")
    assert unverified_subject(f"Bearer {token}") == "a-real-user-id"


def test_unverified_subject_returns_none_for_missing_or_malformed_input():
    assert unverified_subject(None) is None
    assert unverified_subject("not-a-bearer-header") is None
    assert unverified_subject("Bearer not.a.realtoken.at.all") is None
    assert unverified_subject("Bearer garbage") is None
