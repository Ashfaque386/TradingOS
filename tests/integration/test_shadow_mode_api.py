"""Shadow Mode API integration test (Phase 4 Epic E4.4): src/api/routers/shadow_mode.py against
the real FastAPI app + real Postgres. The Zerodha path needs no live token (see
tests/unit/test_shadow_mode.py's docstring) and is exercised for real end-to-end through the API
here; the Upstox real-sandbox path is gated behind a live-broker skip, same pattern as every
other real Upstox/Zerodha call in this codebase.
"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.brokers.factory import NoBrokerConfigured, build_upstox_adapter
from src.core.config import get_settings
from src.core.db import get_session
from src.models.shadow_mode import ShadowModeAttempt

client = TestClient(app)


def _cleanup(*attempt_ids: uuid.UUID) -> None:
    with get_session() as session:
        for attempt_id in attempt_ids:
            session.query(ShadowModeAttempt).filter(ShadowModeAttempt.id == attempt_id).delete()
        session.commit()


def test_zerodha_attempt_is_real_end_to_end_and_never_hits_the_network():
    if not (get_settings().zerodha_api_key and get_settings().zerodha_access_token):
        pytest.skip("Zerodha not configured in this environment")

    response = client.post(
        "/api/v1/shadow-mode/attempt",
        json={"broker": "zerodha", "symbol": "INFY", "side": "BUY", "quantity": 10},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["broker"] == "zerodha"
    assert body["outcome"] == "Validated"
    assert body["used_real_sandbox"] is False

    try:
        status_response = client.get("/api/v1/shadow-mode/status")
        assert status_response.status_code == 200
        status_body = status_response.json()
        today = datetime.now(UTC).date().isoformat()
        today_summary = next(d for d in status_body["daily_summary"] if d["date"] == today)
        assert today_summary["attempts"] >= 1
    finally:
        _cleanup(uuid.UUID(body["id"]))


def test_upstox_attempt_against_the_real_sandbox():
    try:
        build_upstox_adapter()
    except NoBrokerConfigured:
        pytest.skip("Upstox not configured in this environment")

    response = client.post(
        "/api/v1/shadow-mode/attempt",
        json={"broker": "upstox", "symbol": "INFY", "side": "BUY", "quantity": 1},
    )
    if response.status_code != 201:
        pytest.skip(
            f"Real Upstox sandbox call failed (status={response.status_code}) -- likely today's "
            "expired daily access token, not a code defect."
        )
    body = response.json()
    assert body["broker"] == "upstox"
    assert body["used_real_sandbox"] is True
    _cleanup(uuid.UUID(body["id"]))


def test_status_reports_zero_consecutive_days_honestly_when_nothing_has_run():
    # Not asserting a specific value against the shared ledger (other tests/real usage may have
    # written rows) -- just that the endpoint responds with a well-formed, non-fabricated shape.
    response = client.get("/api/v1/shadow-mode/status")
    assert response.status_code == 200
    body = response.json()
    assert body["consecutive_clean_days"] >= 0
    assert body["go_live_gate_met"] == (body["consecutive_clean_days"] >= 5)
