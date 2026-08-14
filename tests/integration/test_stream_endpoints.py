"""WebSocket streaming endpoint tests (Phase 4 Epic E4.2), per Phase_10_API_Design.md §16
(API-091 market ticks, API-092 agent logs): a real tick/log is published to the real dockerized
Redis and must arrive over the WebSocket connection reshaped to the documented payload.
"""

import json
import time
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from src.api.main import app
from src.engine.risk.ws_latency_guard_service import get_latency_guard
from src.memory.redis_client import (
    get_redis_client,
    publish_agent_log,
    publish_order_event,
    publish_tick,
)


def test_market_stream_relays_a_real_published_tick():
    client = TestClient(app)
    with client.websocket_connect("/api/v1/stream/market/RELIANCE") as websocket:
        redis_client = get_redis_client()
        time.sleep(0.2)  # let the server's subscribe land before publishing
        publish_tick(
            redis_client,
            "RELIANCE",
            json.dumps({"price": 2500.5, "volume": 100, "timestamp": "2026-01-15T10:00:00+00:00"}),
        )

        message = websocket.receive_json()

    assert message == {
        "symbol": "RELIANCE",
        "ltp": 2500.5,
        "volume": 100,
        "ts": "2026-01-15T10:00:00+00:00",
    }


def test_market_stream_defaults_volume_to_zero_when_absent():
    client = TestClient(app)
    with client.websocket_connect("/api/v1/stream/market/TCS") as websocket:
        redis_client = get_redis_client()
        time.sleep(0.2)
        publish_tick(redis_client, "TCS", json.dumps({"price": 3500.0}))

        message = websocket.receive_json()

    assert message["symbol"] == "TCS"
    assert message["ltp"] == 3500.0
    assert message["volume"] == 0


def test_agent_logs_stream_relays_a_real_published_log():
    client = TestClient(app)
    with client.websocket_connect("/api/v1/stream/agents/logs") as websocket:
        redis_client = get_redis_client()
        time.sleep(0.2)
        payload = {
            "agent_id": "AGT-001",
            "node": "ceo_agent",
            "message": "Generating today's Executive Research Directive",
            "ts": "2026-01-15T10:00:00+00:00",
        }
        publish_agent_log(redis_client, json.dumps(payload))

        received = websocket.receive_text()

    assert json.loads(received) == payload


def test_order_events_stream_relays_a_real_published_event():
    """REL-061 (API-093). Same verbatim-relay shape as /agents/logs above -- the real publisher
    is src/api/routers/orders.py's place_order()/cancel_order(), verified separately in
    tests/integration/test_orders_api.py; this only proves the relay side."""
    client = TestClient(app)
    with client.websocket_connect("/api/v1/stream/orders") as websocket:
        redis_client = get_redis_client()
        time.sleep(0.2)
        payload = {
            "account_scope": "Live",
            "order_id": "11111111-1111-1111-1111-111111111111",
            "broker_order_id": "BROKER-ORDER-9",
            "symbol": "RELIANCE",
            "side": "BUY",
            "quantity": 10,
            "status": "OPEN",
            "ts": "2026-01-15T10:00:00+00:00",
        }
        publish_order_event(redis_client, json.dumps(payload))

        received = websocket.receive_text()

    assert json.loads(received) == payload


def test_market_stream_relay_latency_stays_low():
    client = TestClient(app)
    with client.websocket_connect("/api/v1/stream/market/LATENCYTEST") as websocket:
        redis_client = get_redis_client()
        time.sleep(0.2)

        start = time.perf_counter()
        publish_tick(redis_client, "LATENCYTEST", json.dumps({"price": 100.0}))
        websocket.receive_json()
        elapsed = time.perf_counter() - start

    assert elapsed < 0.1, f"WS relay round-trip was {elapsed * 1000:.1f}ms (budget 100ms)"


def test_a_stale_tick_pauses_the_shared_latency_guard_and_a_fresh_one_resumes_it():
    guard = get_latency_guard()
    guard.record(0.01)  # start from a known-good state
    assert guard.paused is False

    client = TestClient(app)
    with client.websocket_connect("/api/v1/stream/market/GUARDTEST") as websocket:
        redis_client = get_redis_client()
        time.sleep(0.2)

        stale_timestamp = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        publish_tick(
            redis_client, "GUARDTEST", json.dumps({"price": 100.0, "timestamp": stale_timestamp})
        )
        websocket.receive_json()
        assert guard.paused is True

        fresh_timestamp = datetime.now(UTC).isoformat()
        publish_tick(
            redis_client, "GUARDTEST", json.dumps({"price": 101.0, "timestamp": fresh_timestamp})
        )
        websocket.receive_json()

    assert guard.paused is False


def test_metrics_endpoint_exposes_the_ws_latency_histogram():
    client = TestClient(app)

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "tradingos_ws_stream_latency_seconds" in response.text
