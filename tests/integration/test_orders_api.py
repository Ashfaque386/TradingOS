"""Live Order/Trade API integration test (REL-018 E18.1): src/api/routers/orders.py against the
real FastAPI app + real Postgres. Mirrors tests/integration/test_paper_trading_api.py's own
seed/cleanup pattern, over the real ORDERS/TRADES tables instead of the paper ledger.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from src.api.main import app
from src.core.db import get_session
from src.models.account import Account
from src.models.strategy import Strategy
from src.models.trading import Order, Trade
from src.models.user import User

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
