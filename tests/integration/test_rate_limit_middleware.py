"""RateLimitMiddleware (REL-064, API-014) against the real FastAPI app + real Redis.

Disabled by default for the whole pytest session (tests/conftest.py sets
API_RATE_LIMIT_ENABLED=false before the app is ever imported) -- every test here explicitly
re-enables it via a patched Settings object for just that test, rather than relying on the
process-wide env var, so the rest of the suite stays unaffected.
"""

from fastapi.testclient import TestClient

from src.api.main import app
from src.core.config import Settings
from src.core.security import ROLE_READ_ONLY_AUDITOR
from src.memory.redis_client import get_redis_client
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)


def _enable_tight_limit(monkeypatch, limit: int = 2, window_seconds: int = 60) -> None:
    patched = Settings(
        api_rate_limit_enabled=True,
        api_rate_limit_requests=limit,
        api_rate_limit_window_seconds=window_seconds,
    )
    monkeypatch.setattr("src.core.rate_limit_middleware.get_settings", lambda: patched)
    monkeypatch.setattr("src.api.routers.system.get_settings", lambda: patched)


def _clear_bucket(caller_key: str) -> None:
    redis_client = get_redis_client()
    for key in redis_client.keys(f"api:ratelimit:{caller_key}:*"):
        redis_client.delete(key)


def test_disabled_by_default_this_pytest_session_never_429s_a_normal_call():
    response = client.get("/health")
    assert response.status_code == 200


def test_exceeding_the_budget_returns_429_with_retry_after(monkeypatch):
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    _enable_tight_limit(monkeypatch, limit=2)
    try:
        r1 = client.get("/api/v1/system/kill-switch/status", headers=auth_header(token))
        r2 = client.get("/api/v1/system/kill-switch/status", headers=auth_header(token))
        r3 = client.get("/api/v1/system/kill-switch/status", headers=auth_header(token))
        assert [r1.status_code, r2.status_code] == [200, 200]
        assert r3.status_code == 429
        assert r3.json()["detail"] == "Rate limit exceeded"
        assert r3.headers.get("Retry-After") == "60"
    finally:
        _clear_bucket(f"user:{user_id}")
        cleanup_user(user_id)


def test_a_429_still_carries_real_cors_headers_not_an_opaque_failure(monkeypatch):
    """Proves the middleware-ordering fix in main.py: RateLimitMiddleware is registered before
    CORSMiddleware (innermost), so its 429 still bubbles up through CORS -- registered the other
    way around, a rate-limited cross-origin call from the real dashboard would see an opaque CORS
    failure instead of a readable 429 body."""
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    _enable_tight_limit(monkeypatch, limit=1)
    try:
        headers = {**auth_header(token), "Origin": "http://localhost:3000"}
        client.get("/api/v1/system/kill-switch/status", headers=headers)
        blocked = client.get("/api/v1/system/kill-switch/status", headers=headers)
        assert blocked.status_code == 429
        assert blocked.headers.get("access-control-allow-origin") == "http://localhost:3000"
    finally:
        _clear_bucket(f"user:{user_id}")
        cleanup_user(user_id)


def test_different_callers_do_not_share_a_budget(monkeypatch):
    user_a, token_a = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    user_b, token_b = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    _enable_tight_limit(monkeypatch, limit=1)
    try:
        a1 = client.get("/api/v1/system/kill-switch/status", headers=auth_header(token_a))
        a2 = client.get("/api/v1/system/kill-switch/status", headers=auth_header(token_a))
        b1 = client.get("/api/v1/system/kill-switch/status", headers=auth_header(token_b))
        assert a1.status_code == 200
        assert a2.status_code == 429
        assert b1.status_code == 200, "a fresh caller must not inherit another caller's usage"
    finally:
        _clear_bucket(f"user:{user_a}")
        _clear_bucket(f"user:{user_b}")
        cleanup_user(user_a)
        cleanup_user(user_b)


def test_health_endpoint_is_exempt_from_enforcement(monkeypatch):
    _enable_tight_limit(monkeypatch, limit=1)
    for _ in range(5):
        assert client.get("/health").status_code == 200


def test_rate_limit_status_reports_real_remaining_budget(monkeypatch):
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    _enable_tight_limit(monkeypatch, limit=5)
    try:
        client.get("/api/v1/system/kill-switch/status", headers=auth_header(token))
        client.get("/api/v1/system/kill-switch/status", headers=auth_header(token))
        response = client.get("/api/v1/system/rate-limit/status", headers=auth_header(token))
        assert response.status_code == 200
        body = response.json()
        assert body["limit"] == 5
        # 2 prior calls + this status call itself all consume from the same real counter.
        assert body["remaining"] == 2
        assert body["window_seconds"] == 60
    finally:
        _clear_bucket(f"user:{user_id}")
        cleanup_user(user_id)


def test_rate_limit_status_requires_authentication():
    response = client.get("/api/v1/system/rate-limit/status")
    assert response.status_code == 401


def test_unauthenticated_callers_are_rate_limited_by_ip(monkeypatch):
    _enable_tight_limit(monkeypatch, limit=1)
    try:
        r1 = client.get("/api/v1/system/kill-switch/status")
        r2 = client.get("/api/v1/system/kill-switch/status")
        assert r1.status_code == 200
        assert r2.status_code == 429
    finally:
        redis_client = get_redis_client()
        for key in redis_client.keys("api:ratelimit:ip:*"):
            redis_client.delete(key)
