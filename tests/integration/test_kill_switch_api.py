"""Kill Switch API integration test (Phase 3 Epic E3.4): the endpoints wired in
src/api/routers/system.py (API-084/085/086, Phase_10_API_Design.md §14) against the real
FastAPI app + real Postgres.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from src.api.main import app
from src.core.db import get_session
from src.core.security import ROLE_SYSTEM_ADMINISTRATOR
from src.engine.risk import kill_switch_service
from src.models.account import Account
from src.models.audit import AuditLog
from src.models.strategy import Strategy
from src.models.trading import Order, PortfolioPosition
from src.models.user import User
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)


def _create_fixture_rows() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    user_id, account_id, strategy_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    order_id, position_id = uuid.uuid4(), uuid.uuid4()

    with get_session() as session:
        session.add(
            User(
                id=user_id,
                email=f"kill-switch-api-{user_id}@example.invalid",
                hashed_password="x",
                role="Trader",
            )
        )
        session.commit()

    with get_session() as session:
        session.add(
            Account(
                id=account_id,
                user_id=user_id,
                broker="Zerodha",
                account_type="Paper",
                capital_allocated=Decimal("100000.00"),
            )
        )
        session.commit()

    with get_session() as session:
        session.add(
            Strategy(
                id=strategy_id,
                account_id=account_id,
                name="kill-switch-api-test-strategy",
                asset_class="Equity",
                style="Intraday",
                status="Live",
                max_drawdown_limit=Decimal("15.00"),
            )
        )
        session.commit()

    with get_session() as session:
        session.add(
            Order(
                id=order_id,
                account_id=account_id,
                strategy_id=strategy_id,
                symbol="RELIANCE",
                side="BUY",
                order_type="MARKET",
                quantity=10,
                status="PENDING",
                requested_at=datetime.now(UTC),
            )
        )
        session.add(
            PortfolioPosition(
                id=position_id,
                account_id=account_id,
                strategy_id=strategy_id,
                symbol="RELIANCE",
                net_quantity=10,
                avg_price=Decimal("2500.00"),
                as_of=datetime.now(UTC),
            )
        )
        session.commit()

    return user_id, account_id, strategy_id, order_id, position_id


def _cleanup_fixture_rows(
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    strategy_id: uuid.UUID,
    order_id: uuid.UUID,
    position_id: uuid.UUID,
) -> None:
    with get_session() as session:
        session.query(Order).filter(Order.id == order_id).delete()
        session.query(PortfolioPosition).filter(PortfolioPosition.id == position_id).delete()
        session.query(Strategy).filter(Strategy.id == strategy_id).delete()
        session.query(Account).filter(Account.id == account_id).delete()
        session.query(User).filter(User.id == user_id).delete()
        session.commit()


def test_kill_switch_trip_status_and_reset_end_to_end():
    ids = _create_fixture_rows()
    user_id, account_id, strategy_id, order_id, position_id = ids
    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    headers = auth_header(admin_token)

    try:
        status_before = client.get("/api/v1/system/kill-switch/status")
        assert status_before.json()["state"] == "ARMED"

        trip_response = client.post(
            "/api/v1/system/kill-switch", json={"reason": "integration test"}, headers=headers
        )
        assert trip_response.status_code == 200
        body = trip_response.json()
        assert body["status"] == "TRIPPED"
        assert body["liquidated_positions"] >= 1

        with get_session() as session:
            order = session.get(Order, order_id)
            position = session.get(PortfolioPosition, position_id)
            assert order.status == "CANCELLED"
            assert position.net_quantity == 0

        status_after_trip = client.get("/api/v1/system/kill-switch/status")
        assert status_after_trip.json()["state"] == "TRIPPED"
        assert status_after_trip.json()["tripped_at"] is not None

        with get_session() as session:
            audit_rows = list(
                session.query(AuditLog)
                .filter(AuditLog.action == "KILL_SWITCH_TRIPPED")
                .order_by(AuditLog.id.desc())
                .limit(1)
            )
            assert len(audit_rows) == 1
            assert audit_rows[0].entry_hash is not None

        reset_without_confirmation = client.post(
            "/api/v1/system/kill-switch/reset", json={"confirmation": False}, headers=headers
        )
        assert reset_without_confirmation.status_code == 400

        reset_response = client.post(
            "/api/v1/system/kill-switch/reset", json={"confirmation": True}, headers=headers
        )
        assert reset_response.status_code == 200
        assert reset_response.json()["status"] == "ARMED"

        status_after_reset = client.get("/api/v1/system/kill-switch/status")
        assert status_after_reset.json()["state"] == "ARMED"
    finally:
        with get_session() as session:
            kill_switch_service.reset(session)
        _cleanup_fixture_rows(*ids)
        cleanup_user(admin_id)
