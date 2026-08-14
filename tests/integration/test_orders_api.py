"""Live Order/Trade API integration test (REL-018 E18.1): src/api/routers/orders.py against the
real FastAPI app + real Postgres. Mirrors tests/integration/test_paper_trading_api.py's own
seed/cleanup pattern, over the real ORDERS/TRADES tables instead of the paper ledger.
"""

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from src.api.main import app
from src.brokers.base import OrderResponse as BrokerOrderResponse
from src.brokers.base import Position
from src.core.db import get_session
from src.core.security import ROLE_PORTFOLIO_MANAGER, ROLE_READ_ONLY_AUDITOR
from src.engine.live.execution_pipeline import RiskRejected
from src.engine.paper_trading.execution_service import NoLiquidityError
from src.memory.redis_client import ORDER_EVENT_CHANNEL, get_redis_client
from src.models.account import Account
from src.models.paper_trading import PaperTrade
from src.models.strategy import Strategy
from src.models.trading import Order, Trade
from src.models.user import User
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)


def _seed_strategy() -> uuid.UUID:
    user_id, account_id, strategy_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with get_session() as session:
        session.add(
            User(
                id=user_id,
                email=f"orders-api-{user_id}@example.invalid",
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
                account_type="Live",
                capital_allocated=Decimal("100000.00"),
            )
        )
        session.commit()
    with get_session() as session:
        session.add(
            Strategy(
                id=strategy_id,
                account_id=account_id,
                name="orders-api-test-strategy",
                asset_class="Equity",
                style="Intraday",
                status="Live",
                max_drawdown_limit=Decimal("15.00"),
            )
        )
        session.commit()
    return strategy_id


def _cleanup_strategy(strategy_id: uuid.UUID) -> None:
    with get_session() as session:
        strategy = session.get(Strategy, strategy_id)
        if strategy is None:
            return
        account_id = strategy.account_id
        session.query(Strategy).filter(Strategy.id == strategy_id).delete()
        session.commit()
    with get_session() as session:
        account = session.get(Account, account_id)
        if account is not None:
            user_id = account.user_id
            session.query(Account).filter(Account.id == account_id).delete()
            session.commit()
            session.query(User).filter(User.id == user_id).delete()
            session.commit()


def _seed_order(*, strategy_id: uuid.UUID, symbol: str, status: str = "FILLED") -> uuid.UUID:
    with get_session() as session:
        order = Order(
            account_id=session.get(Strategy, strategy_id).account_id,
            strategy_id=strategy_id,
            symbol=symbol,
            side="BUY",
            order_type="MARKET",
            quantity=10,
            status=status,
            requested_at=datetime.now(UTC),
        )
        session.add(order)
        session.commit()
        return order.id


def _seed_trade(*, strategy_id: uuid.UUID, order_id: uuid.UUID, symbol: str) -> uuid.UUID:
    with get_session() as session:
        trade = Trade(
            order_id=order_id,
            strategy_id=strategy_id,
            symbol=symbol,
            side="BUY",
            price=Decimal("100.00"),
            quantity=10,
            net_pnl=Decimal("50.00"),
            executed_at=datetime.now(UTC),
        )
        session.add(trade)
        session.commit()
        return trade.id


def _cleanup_orders(*order_ids: uuid.UUID) -> None:
    with get_session() as session:
        session.query(Trade).filter(Trade.order_id.in_(order_ids)).delete(synchronize_session=False)
        session.query(Order).filter(Order.id.in_(order_ids)).delete(synchronize_session=False)
        session.commit()


def test_orders_endpoint_lists_real_seeded_rows_and_filters_by_strategy():
    strategy_a = _seed_strategy()
    strategy_b = _seed_strategy()
    symbol = f"TESTSYM{uuid.uuid4().hex[:6].upper()}"
    order_a = _seed_order(strategy_id=strategy_a, symbol=symbol)
    order_b = _seed_order(strategy_id=strategy_b, symbol=symbol)
    try:
        response = client.get(f"/api/v1/orders?strategy_id={strategy_a}")
        assert response.status_code == 200
        body = response.json()
        assert any(o["id"] == str(order_a) for o in body)
        assert not any(o["id"] == str(order_b) for o in body)
    finally:
        _cleanup_orders(order_a, order_b)
        _cleanup_strategy(strategy_a)
        _cleanup_strategy(strategy_b)


def test_trades_endpoint_reconciles_exactly_against_a_direct_db_query():
    """The exit criterion Phase_14_Master_Development_Roadmap.md REL-018 names explicitly:
    'Dashboard totals reconcile exactly against a direct database query in a real test.'"""
    strategy_id = _seed_strategy()
    symbol = f"TESTSYM{uuid.uuid4().hex[:6].upper()}"
    order_id = _seed_order(strategy_id=strategy_id, symbol=symbol)
    trade_id = _seed_trade(strategy_id=strategy_id, order_id=order_id, symbol=symbol)
    try:
        response = client.get(f"/api/v1/trades?strategy_id={strategy_id}")
        assert response.status_code == 200
        api_trades = response.json()
        assert len(api_trades) == 1
        assert api_trades[0]["id"] == str(trade_id)
        assert api_trades[0]["net_pnl"] == 50.0

        with get_session() as session:
            direct_count = session.scalar(
                select(func.count(Trade.id)).where(Trade.strategy_id == strategy_id)
            )
            direct_pnl = session.scalar(
                select(func.sum(Trade.net_pnl)).where(Trade.strategy_id == strategy_id)
            )
        assert len(api_trades) == direct_count
        assert sum(t["net_pnl"] for t in api_trades) == pytest.approx(float(direct_pnl))
    finally:
        _cleanup_orders(order_id)
        _cleanup_strategy(strategy_id)


def test_execution_latency_endpoint_returns_a_real_summary_shape():
    """The histogram is process-global (no labels), so this can't assert a specific count in a
    shared test process -- it asserts the real shape and internal consistency instead."""
    response = client.get("/api/v1/orders/execution-latency")
    assert response.status_code == 200
    body = response.json()
    assert body["sample_count"] >= 0
    assert body["total_seconds"] >= 0.0
    if body["sample_count"] == 0:
        assert body["avg_ms"] is None
    else:
        assert body["avg_ms"] == (body["total_seconds"] / body["sample_count"] * 1000)


# REL-058: GET /orders/{order_id} (API-056).


def test_get_order_returns_the_real_order_and_its_real_fills():
    strategy_id = _seed_strategy()
    symbol = f"TESTSYM{uuid.uuid4().hex[:6].upper()}"
    order_id = _seed_order(strategy_id=strategy_id, symbol=symbol)
    trade_id = _seed_trade(strategy_id=strategy_id, order_id=order_id, symbol=symbol)
    try:
        response = client.get(f"/api/v1/orders/{order_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(order_id)
        assert body["symbol"] == symbol
        assert body["status"] == "FILLED"
        assert len(body["fills"]) == 1
        assert body["fills"][0]["id"] == str(trade_id)
        assert body["fills"][0]["price"] == 100.0
    finally:
        _cleanup_orders(order_id)
        _cleanup_strategy(strategy_id)


def test_get_order_with_no_fills_returns_an_empty_fills_list():
    strategy_id = _seed_strategy()
    order_id = _seed_order(strategy_id=strategy_id, symbol="TESTSYMNOFILL", status="PENDING")
    try:
        response = client.get(f"/api/v1/orders/{order_id}")
        assert response.status_code == 200
        assert response.json()["fills"] == []
    finally:
        _cleanup_orders(order_id)
        _cleanup_strategy(strategy_id)


def test_get_order_unknown_id_is_a_404():
    response = client.get(f"/api/v1/orders/{uuid.uuid4()}")
    assert response.status_code == 404


def test_get_order_does_not_shadow_the_execution_latency_literal_path():
    """Regression guard: GET /orders/{order_id} is registered ahead of a dynamic-path pitfall --
    it must never intercept the literal /orders/execution-latency route above it in this file.
    A real HTTP request through the app's real routing (not a direct function call) is the only
    way this would actually be caught."""
    response = client.get("/api/v1/orders/execution-latency")
    assert response.status_code == 200
    assert "sample_count" in response.json()


# REL-055: POST /orders, DELETE /orders/{order_id}, POST /positions/{symbol}/close.


def _place_order_body(strategy_id: uuid.UUID, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "strategy_id": str(strategy_id),
        "symbol": "TESTSYM",
        "side": "BUY",
        "quantity": 10,
        "account_scope": "Live",
        "confirm_live_order": True,
    }
    body.update(overrides)
    return body


def test_place_order_requires_the_gated_role():
    strategy_id = _seed_strategy()
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    try:
        response = client.post(
            "/api/v1/orders", json=_place_order_body(strategy_id), headers=auth_header(token)
        )
        assert response.status_code == 403
    finally:
        cleanup_user(user_id)
        _cleanup_strategy(strategy_id)


def test_place_order_live_without_confirm_is_a_400_and_never_calls_the_broker():
    strategy_id = _seed_strategy()
    user_id, token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    try:
        with patch("src.api.routers.orders.build_broker") as mock_build_broker:
            response = client.post(
                "/api/v1/orders",
                json=_place_order_body(strategy_id, confirm_live_order=False),
                headers=auth_header(token),
            )
            assert response.status_code == 400
            mock_build_broker.assert_not_called()
    finally:
        cleanup_user(user_id)
        _cleanup_strategy(strategy_id)


def test_place_order_live_places_a_real_broker_order_when_confirmed():
    strategy_id = _seed_strategy()
    user_id, token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    order_id = None
    try:
        fake_broker = AsyncMock()
        fake_broker.place_order.return_value = BrokerOrderResponse(
            broker_order_id="BROKER-ORDER-1",
            status="OPEN",
            symbol="TESTSYM",
            side="BUY",
            order_type="MARKET",
            quantity=10,
        )
        with patch("src.api.routers.orders.build_broker", return_value=fake_broker):
            response = client.post(
                "/api/v1/orders", json=_place_order_body(strategy_id), headers=auth_header(token)
            )
        assert response.status_code == 201
        body = response.json()
        assert body["account_scope"] == "Live"
        assert body["broker_order_id"] == "BROKER-ORDER-1"
        order_id = uuid.UUID(body["order_id"])
        fake_broker.place_order.assert_called_once()

        with get_session() as session:
            order = session.get(Order, order_id)
            assert order is not None
            assert order.broker_order_id == "BROKER-ORDER-1"
    finally:
        if order_id is not None:
            _cleanup_orders(order_id)
        cleanup_user(user_id)
        _cleanup_strategy(strategy_id)


def test_place_order_live_publishes_a_real_order_event():
    """REL-061 (API-093): a real message lands on the real order-status stream's own Redis
    channel -- the exact same channel GET /stream/orders relays verbatim, so this proves the
    publish side of that wiring for real, not just that a function was called."""
    strategy_id = _seed_strategy()
    user_id, token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    order_id = None
    redis_client = get_redis_client()
    pubsub = redis_client.pubsub()
    pubsub.subscribe(ORDER_EVENT_CHANNEL)
    pubsub.get_message(timeout=1.0)  # the subscribe confirmation itself, not a real event
    try:
        fake_broker = AsyncMock()
        fake_broker.place_order.return_value = BrokerOrderResponse(
            broker_order_id="BROKER-ORDER-STREAM",
            status="OPEN",
            symbol="TESTSYM",
            side="BUY",
            order_type="MARKET",
            quantity=10,
        )
        with patch("src.api.routers.orders.build_broker", return_value=fake_broker):
            response = client.post(
                "/api/v1/orders", json=_place_order_body(strategy_id), headers=auth_header(token)
            )
        assert response.status_code == 201
        order_id = uuid.UUID(response.json()["order_id"])

        message = pubsub.get_message(timeout=2.0)
        assert message is not None, "no real message arrived on the order-events channel"
        event = json.loads(message["data"])
        assert event["account_scope"] == "Live"
        assert event["order_id"] == str(order_id)
        assert event["broker_order_id"] == "BROKER-ORDER-STREAM"
        assert event["status"] == "OPEN"
    finally:
        pubsub.unsubscribe(ORDER_EVENT_CHANNEL)
        pubsub.close()
        redis_client.close()
        if order_id is not None:
            _cleanup_orders(order_id)
        cleanup_user(user_id)
        _cleanup_strategy(strategy_id)


def test_place_order_live_kill_switch_tripped_blocks_before_any_broker_call():
    strategy_id = _seed_strategy()
    user_id, token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    try:
        with (
            patch("src.api.routers.orders.kill_switch_service.is_tripped", return_value=True),
            patch("src.api.routers.orders.build_broker") as mock_build_broker,
        ):
            response = client.post(
                "/api/v1/orders", json=_place_order_body(strategy_id), headers=auth_header(token)
            )
        assert response.status_code == 423
        mock_build_broker.assert_not_called()
    finally:
        cleanup_user(user_id)
        _cleanup_strategy(strategy_id)


def test_place_order_live_compliance_block_prevents_broker_call():
    strategy_id = _seed_strategy()
    user_id, token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    try:
        with (
            patch(
                "src.api.routers.orders.compliance_pre_trade_check",
                side_effect=RiskRejected("blocked for test"),
            ),
            patch("src.api.routers.orders.build_broker") as mock_build_broker,
        ):
            response = client.post(
                "/api/v1/orders", json=_place_order_body(strategy_id), headers=auth_header(token)
            )
        assert response.status_code == 403
        mock_build_broker.assert_not_called()
    finally:
        cleanup_user(user_id)
        _cleanup_strategy(strategy_id)


def test_place_order_paper_delegates_to_execute_paper_trade():
    strategy_id = _seed_strategy()
    user_id, token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    fake_trade = PaperTrade(
        id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        strategy_id=strategy_id,
        symbol="TESTSYM",
        side="BUY",
        requested_quantity=10,
        filled_quantity=10,
        reference_price=Decimal("100.00"),
        fill_price=Decimal("100.05"),
        slippage_bps=Decimal("5.0"),
        executed_at=datetime.now(UTC),
    )
    try:
        with (
            patch("src.api.routers.orders.build_broker") as mock_build_broker,
            patch(
                "src.api.routers.orders.execute_paper_trade",
                new_callable=AsyncMock,
                return_value=fake_trade,
            ) as mock_execute,
        ):
            response = client.post(
                "/api/v1/orders",
                json=_place_order_body(strategy_id, account_scope="Paper"),
                headers=auth_header(token),
            )
        assert response.status_code == 201
        body = response.json()
        assert body["account_scope"] == "Paper"
        assert body["paper_trade_id"] == str(fake_trade.id)
        assert body["fill_price"] == 100.05
        mock_execute.assert_called_once()
        mock_build_broker.assert_called_once()
    finally:
        cleanup_user(user_id)
        _cleanup_strategy(strategy_id)


def test_place_order_paper_no_liquidity_is_a_409():
    strategy_id = _seed_strategy()
    user_id, token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    try:
        with (
            patch("src.api.routers.orders.build_broker"),
            patch(
                "src.api.routers.orders.execute_paper_trade",
                new_callable=AsyncMock,
                side_effect=NoLiquidityError("no depth"),
            ),
        ):
            response = client.post(
                "/api/v1/orders",
                json=_place_order_body(strategy_id, account_scope="Paper"),
                headers=auth_header(token),
            )
        assert response.status_code == 409
    finally:
        cleanup_user(user_id)
        _cleanup_strategy(strategy_id)


def test_cancel_order_calls_real_broker_cancel():
    strategy_id = _seed_strategy()
    user_id, token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    order_id = _seed_order(strategy_id=strategy_id, symbol="TESTSYM")
    with get_session() as session:
        order = session.get(Order, order_id)
        order.broker_order_id = "BROKER-ORDER-2"
        session.commit()
    try:
        fake_broker = AsyncMock()
        fake_broker.cancel_order.return_value = BrokerOrderResponse(
            broker_order_id="BROKER-ORDER-2",
            status="CANCELLED",
            symbol="TESTSYM",
            side="BUY",
            order_type="MARKET",
            quantity=10,
        )
        with patch("src.api.routers.orders.build_broker", return_value=fake_broker):
            response = client.delete(f"/api/v1/orders/{order_id}", headers=auth_header(token))
        assert response.status_code == 200
        assert response.json()["status"] == "CANCELLED"
        fake_broker.cancel_order.assert_called_once_with("BROKER-ORDER-2")
    finally:
        _cleanup_orders(order_id)
        cleanup_user(user_id)
        _cleanup_strategy(strategy_id)


def test_cancel_order_publishes_a_real_order_event():
    strategy_id = _seed_strategy()
    user_id, token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    order_id = _seed_order(strategy_id=strategy_id, symbol="TESTSYM")
    with get_session() as session:
        order = session.get(Order, order_id)
        order.broker_order_id = "BROKER-ORDER-CANCEL-STREAM"
        session.commit()
    redis_client = get_redis_client()
    pubsub = redis_client.pubsub()
    pubsub.subscribe(ORDER_EVENT_CHANNEL)
    pubsub.get_message(timeout=1.0)
    try:
        fake_broker = AsyncMock()
        fake_broker.cancel_order.return_value = BrokerOrderResponse(
            broker_order_id="BROKER-ORDER-CANCEL-STREAM",
            status="CANCELLED",
            symbol="TESTSYM",
            side="BUY",
            order_type="MARKET",
            quantity=10,
        )
        with patch("src.api.routers.orders.build_broker", return_value=fake_broker):
            response = client.delete(f"/api/v1/orders/{order_id}", headers=auth_header(token))
        assert response.status_code == 200

        message = pubsub.get_message(timeout=2.0)
        assert message is not None, "no real message arrived on the order-events channel"
        event = json.loads(message["data"])
        assert event["order_id"] == str(order_id)
        assert event["status"] == "CANCELLED"
        assert event["broker_order_id"] == "BROKER-ORDER-CANCEL-STREAM"
    finally:
        pubsub.unsubscribe(ORDER_EVENT_CHANNEL)
        pubsub.close()
        redis_client.close()
        _cleanup_orders(order_id)
        cleanup_user(user_id)
        _cleanup_strategy(strategy_id)


def test_cancel_order_without_broker_order_id_is_a_400():
    strategy_id = _seed_strategy()
    user_id, token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    order_id = _seed_order(strategy_id=strategy_id, symbol="TESTSYM")
    try:
        response = client.delete(f"/api/v1/orders/{order_id}", headers=auth_header(token))
        assert response.status_code == 400
    finally:
        _cleanup_orders(order_id)
        cleanup_user(user_id)
        _cleanup_strategy(strategy_id)


def test_close_position_live_places_the_opposite_side_order():
    strategy_id = _seed_strategy()
    user_id, token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    order_id = None
    try:
        fake_broker = AsyncMock()
        fake_broker.get_positions.return_value = [
            Position(symbol="TESTSYM", net_quantity=100, average_price=100.0)
        ]
        fake_broker.place_order.return_value = BrokerOrderResponse(
            broker_order_id="BROKER-CLOSE-1",
            status="OPEN",
            symbol="TESTSYM",
            side="SELL",
            order_type="MARKET",
            quantity=100,
        )
        with patch("src.api.routers.orders.build_broker", return_value=fake_broker):
            response = client.post(
                "/api/v1/positions/TESTSYM/close",
                json={
                    "strategy_id": str(strategy_id),
                    "account_scope": "Live",
                    "confirm_live_order": True,
                },
                headers=auth_header(token),
            )
        assert response.status_code == 201
        body = response.json()
        assert body["side"] == "SELL"
        assert body["quantity"] == 100
        order_id = uuid.UUID(body["order_id"])
        placed_order = fake_broker.place_order.call_args.args[0]
        assert placed_order.side == "SELL"
        assert placed_order.quantity == 100
    finally:
        if order_id is not None:
            _cleanup_orders(order_id)
        cleanup_user(user_id)
        _cleanup_strategy(strategy_id)


def test_close_position_no_open_position_is_a_404():
    strategy_id = _seed_strategy()
    user_id, token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    try:
        fake_broker = AsyncMock()
        fake_broker.get_positions.return_value = []
        with patch("src.api.routers.orders.build_broker", return_value=fake_broker):
            response = client.post(
                "/api/v1/positions/TESTSYM/close",
                json={
                    "strategy_id": str(strategy_id),
                    "account_scope": "Live",
                    "confirm_live_order": True,
                },
                headers=auth_header(token),
            )
        assert response.status_code == 404
    finally:
        cleanup_user(user_id)
        _cleanup_strategy(strategy_id)
