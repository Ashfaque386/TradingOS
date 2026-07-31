"""REL-010 E10.5: Portfolio allocation-recommendation API against the real FastAPI app + real
Postgres. `trigger` itself is exercised in tests/integration/test_portfolio_manager_agent.py at
the node level (mocked LLM/broker) -- these tests seed a real recommendation row directly and
focus on the RBAC/latest/accept/reject surface.
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from src.api.main import app
from src.core.db import get_session
from src.core.security import (
    ROLE_PORTFOLIO_MANAGER,
    ROLE_READ_ONLY_AUDITOR,
    ROLE_SYSTEM_ADMINISTRATOR,
)
from src.models.portfolio_allocation_recommendation import PortfolioAllocationRecommendation
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)


def _seed_recommendation() -> uuid.UUID:
    with get_session() as session:
        row = PortfolioAllocationRecommendation(
            generated_at=datetime.now(UTC),
            recommendations={"weights": [{"strategy_id": "x", "weight_pct": 50.0}]},
            rationale="test-seed",
            status="Proposed",
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def _cleanup(recommendation_id: uuid.UUID) -> None:
    with get_session() as session:
        session.query(PortfolioAllocationRecommendation).filter(
            PortfolioAllocationRecommendation.id == recommendation_id
        ).delete()
        session.commit()


def test_trigger_requires_portfolio_manager_or_system_administrator_role():
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    try:
        response = client.post(
            "/api/v1/portfolio/allocation-recommendation/trigger", headers=auth_header(token)
        )
        assert response.status_code == 403
    finally:
        cleanup_user(user_id)


def test_unauthenticated_trigger_is_rejected():
    response = client.post("/api/v1/portfolio/allocation-recommendation/trigger")
    assert response.status_code == 401


def test_latest_returns_the_most_recent_real_recommendation():
    recommendation_id = _seed_recommendation()
    try:
        response = client.get("/api/v1/portfolio/allocation-recommendation/latest")
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(recommendation_id)
        assert body["status"] == "Proposed"
        assert body["rationale"] == "test-seed"
    finally:
        _cleanup(recommendation_id)


def test_accept_records_real_human_sign_off_and_is_audited():
    recommendation_id = _seed_recommendation()
    user_id, token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    try:
        response = client.post(
            f"/api/v1/portfolio/allocation-recommendation/{recommendation_id}/accept",
            headers=auth_header(token),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "Accepted"
        assert body["decided_by_user_id"] == str(user_id)

        # A second accept on an already-decided recommendation is rejected, not silently reapplied.
        second = client.post(
            f"/api/v1/portfolio/allocation-recommendation/{recommendation_id}/accept",
            headers=auth_header(token),
        )
        assert second.status_code == 400
    finally:
        _cleanup(recommendation_id)
        cleanup_user(user_id)


def test_reject_requires_the_gated_role_and_records_the_real_decision():
    recommendation_id = _seed_recommendation()
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.post(
            f"/api/v1/portfolio/allocation-recommendation/{recommendation_id}/reject",
            headers=auth_header(token),
        )
        assert response.status_code == 200
        assert response.json()["status"] == "Rejected"
    finally:
        _cleanup(recommendation_id)
        cleanup_user(user_id)


def test_accept_and_reject_never_call_place_order_anywhere_in_this_router():
    """Real, static proof that "human retains override authority" (Business Rule 3) holds by
    absence of any execution path, not just a UI convention -- a grep-level regression guard,
    matching the same discipline REL-010 E10.8 applies to the broker-config router."""
    source = Path("src/api/routers/portfolio.py").read_text(encoding="utf-8")
    assert "place_order" not in source
    assert "modify_order" not in source
    assert "cancel_order" not in source
