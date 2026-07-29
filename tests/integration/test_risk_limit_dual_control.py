"""Dual-control risk-limit change tests (REL-007 E7.4, SEC-013/041) against the real FastAPI
app + real Postgres.
"""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from src.api.main import app
from src.core.security import ROLE_PORTFOLIO_MANAGER, ROLE_READ_ONLY_AUDITOR, ROLE_RISK_MANAGER
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)


def _payload(**overrides: object) -> dict:
    base = {
        "scope_type": "Global",
        "max_daily_loss": 50000.0,
        "max_position_size_pct": 10.0,
        "max_sector_exposure_pct": 25.0,
        "max_drawdown_pct": 15.0,
        "effective_from": datetime.now(UTC).isoformat(),
    }
    base.update(overrides)
    return base


def test_stage_then_confirm_by_a_different_risk_manager_creates_a_real_risk_limit():
    a_id, a_token = create_authenticated_user(ROLE_RISK_MANAGER)
    b_id, b_token = create_authenticated_user(ROLE_RISK_MANAGER)
    try:
        stage = client.post(
            "/api/v1/risk-limits/change-requests",
            json=_payload(max_daily_loss=42000.0),
            headers=auth_header(a_token),
        )
        assert stage.status_code == 200
        request_id = stage.json()["id"]
        assert stage.json()["status"] == "PENDING"

        confirm = client.post(
            f"/api/v1/risk-limits/change-requests/{request_id}/confirm",
            headers=auth_header(b_token),
        )
        assert confirm.status_code == 200
        body = confirm.json()
        assert body["status"] == "APPROVED"
        assert body["resulting_risk_limit_id"] is not None

        current = client.get("/api/v1/risk-limits/current", headers=auth_header(a_token))
        assert current.status_code == 200
        assert current.json()["max_daily_loss"] == 42000.0
    finally:
        cleanup_user(a_id)
        cleanup_user(b_id)


def test_confirming_your_own_staged_change_is_rejected():
    user_id, token = create_authenticated_user(ROLE_RISK_MANAGER)
    try:
        stage = client.post(
            "/api/v1/risk-limits/change-requests", json=_payload(), headers=auth_header(token)
        )
        request_id = stage.json()["id"]

        confirm = client.post(
            f"/api/v1/risk-limits/change-requests/{request_id}/confirm",
            headers=auth_header(token),
        )
        assert confirm.status_code == 403
    finally:
        cleanup_user(user_id)


def test_self_reject_is_allowed_and_creates_no_risk_limit():
    user_id, token = create_authenticated_user(ROLE_RISK_MANAGER)
    try:
        stage = client.post(
            "/api/v1/risk-limits/change-requests",
            json=_payload(max_daily_loss=999999.0),
            headers=auth_header(token),
        )
        request_id = stage.json()["id"]

        reject = client.post(
            f"/api/v1/risk-limits/change-requests/{request_id}/reject",
            json={"reason": "changed my mind"},
            headers=auth_header(token),
        )
        assert reject.status_code == 200
        body = reject.json()
        assert body["status"] == "REJECTED"
        assert body["resulting_risk_limit_id"] is None

        current = client.get("/api/v1/risk-limits/current", headers=auth_header(token))
        assert current.status_code == 200
        assert current.json() is None or current.json()["max_daily_loss"] != 999999.0
    finally:
        cleanup_user(user_id)


def test_portfolio_manager_cannot_stage_a_change():
    user_id, token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    try:
        response = client.post(
            "/api/v1/risk-limits/change-requests", json=_payload(), headers=auth_header(token)
        )
        assert response.status_code == 403
    finally:
        cleanup_user(user_id)


def test_read_only_auditor_can_read_but_not_stage():
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    try:
        read_response = client.get(
            "/api/v1/risk-limits/change-requests", headers=auth_header(token)
        )
        assert read_response.status_code == 200

        write_response = client.post(
            "/api/v1/risk-limits/change-requests", json=_payload(), headers=auth_header(token)
        )
        assert write_response.status_code == 403
    finally:
        cleanup_user(user_id)
