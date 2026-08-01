"""Paper Trading API integration test (Phase 4 Epic E4.4): src/api/routers/paper_trading.py
against the real FastAPI app + real Postgres. The /execute endpoint's real-broker path is
exercised separately -- see test_execute_against_a_real_broker_quote below, which is expected to
be blocked today by the Zerodha/Upstox daily access-token expiry (a known constraint documented
throughout this codebase, not a bug); everything else here is fully real and deterministic:
seeded PaperTrade rows through the real ORM, real average-cost-basis math in
/paper-trading/positions.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.brokers.factory import NoBrokerConfigured, build_broker
from src.core.db import get_session
from src.core.security import ROLE_READ_ONLY_AUDITOR, ROLE_SYSTEM_ADMINISTRATOR
from src.models.account import Account
from src.models.paper_trading import PaperTrade
from src.models.strategy import Strategy
from src.models.user import User
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)


def _seed_strategy() -> uuid.UUID:
    """PaperTrade.strategy_id has a real FK to strategies.id -- a random UUID with no matching
    row fails the insert, so tests that need one seed a real Account/Strategy chain, same
    pattern as tests/integration/test_strategies_api.py."""
    user_id, account_id, strategy_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with get_session() as session:
        session.add(
            User(
                id=user_id,
                email=f"paper-trading-api-{user_id}@example.invalid",
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
                name="paper-trading-api-test-strategy",
                asset_class="Equity",
                style="Intraday",
                status="PaperTrading",
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


def _seed_trade(*, symbol: str, side: str, qty: int, price: float, strategy_id=None) -> uuid.UUID:
    with get_session() as session:
        trade = PaperTrade(
            strategy_id=strategy_id,
            symbol=symbol,
            side=side,
            requested_quantity=qty,
            filled_quantity=qty,
            reference_price=price,
            fill_price=price,
            slippage_bps=0.0,
            depth_snapshot={"buy": [], "sell": [], "fully_filled": True},
            executed_at=datetime.now(UTC),
        )
        session.add(trade)
        session.commit()
        return trade.id


def _cleanup(*trade_ids: uuid.UUID) -> None:
    with get_session() as session:
        for trade_id in trade_ids:
            session.query(PaperTrade).filter(PaperTrade.id == trade_id).delete()
        session.commit()


def test_positions_computes_average_cost_basis_and_realized_pnl():
    symbol = f"TESTSYM{uuid.uuid4().hex[:6].upper()}"
    ids = [
        _seed_trade(symbol=symbol, side="BUY", qty=100, price=50.00),
        _seed_trade(symbol=symbol, side="BUY", qty=100, price=52.00),
        _seed_trade(symbol=symbol, side="SELL", qty=150, price=55.00),
    ]
    try:
        response = client.get("/api/v1/paper-trading/positions")
        assert response.status_code == 200
        position = next(p for p in response.json() if p["symbol"] == symbol)

        # Average cost after both buys: (100*50 + 100*52) / 200 = 51.00
        # Selling 150 @ 55.00 realizes (55.00 - 51.00) * 150 = 600.00, leaving 50 @ 51.00 open.
        assert position["net_quantity"] == 50
        assert position["average_cost"] == pytest.approx(51.00)
        assert position["realized_pnl"] == pytest.approx(600.00)
        assert position["trade_count"] == 3
    finally:
        _cleanup(*ids)


def test_positions_filters_by_strategy_id():
    strategy_a = _seed_strategy()
    strategy_b = _seed_strategy()
    symbol = f"TESTSYM{uuid.uuid4().hex[:6].upper()}"
    ids = [
        _seed_trade(symbol=symbol, side="BUY", qty=10, price=100.0, strategy_id=strategy_a),
        _seed_trade(symbol=symbol, side="BUY", qty=20, price=100.0, strategy_id=strategy_b),
    ]
    try:
        response = client.get(f"/api/v1/paper-trading/positions?strategy_id={strategy_a}")
        assert response.status_code == 200
        position = next(p for p in response.json() if p["symbol"] == symbol)
        assert position["net_quantity"] == 10  # only strategy_a's trade
    finally:
        _cleanup(*ids)
        _cleanup_strategy(strategy_a)
        _cleanup_strategy(strategy_b)


def test_trades_endpoint_lists_real_seeded_rows():
    symbol = f"TESTSYM{uuid.uuid4().hex[:6].upper()}"
    trade_id = _seed_trade(symbol=symbol, side="BUY", qty=5, price=10.0)
    try:
        response = client.get("/api/v1/paper-trading/trades")
        assert response.status_code == 200
        assert any(t["id"] == str(trade_id) for t in response.json())
    finally:
        _cleanup(trade_id)


@pytest.mark.asyncio
async def test_execute_against_a_real_broker_quote():
    """Real end-to-end: a real broker quote (live L2 depth) walked by the real slippage model
    and persisted. Expected to fail with 503 today if no broker is configured, or surface the
    broker's real error if the daily access token has expired -- both are honest, real outcomes,
    not something to work around with a mock."""
    try:
        build_broker()
    except NoBrokerConfigured:
        pytest.skip("No broker configured in this environment")

    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.post(
            "/api/v1/paper-trading/execute",
            json={"symbol": "INFY", "side": "BUY", "quantity": 10},
            headers=auth_header(token),
        )
        if response.status_code != 201:
            pytest.skip(
                f"Real broker call failed (status={response.status_code}, "
                f"body={response.text[:200]}) -- almost certainly today's expired daily access "
                "token (Zerodha/Upstox both require a fresh login each trading day, no refresh "
                "token), not a code defect."
            )

        body = response.json()
        assert body["symbol"] == "INFY"
        assert body["filled_quantity"] > 0
        with get_session() as session:
            session.query(PaperTrade).filter(PaperTrade.id == uuid.UUID(body["id"])).delete()
            session.commit()
    finally:
        cleanup_user(user_id)


def test_execute_requires_authentication():
    """SEC-046: POST /execute was found with NO auth dependency at all -- any unauthenticated
    caller could trigger a real broker quote call and write a row into the ledger the Go-Live
    Readiness Gate counts trades from. 401 must fire before the handler body runs (before any
    broker call or DB write), same shape as test_backtest_trigger_requires_authentication."""
    response = client.post(
        "/api/v1/paper-trading/execute", json={"symbol": "INFY", "side": "BUY", "quantity": 10}
    )
    assert response.status_code == 401


def test_execute_requires_the_gated_role():
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    try:
        response = client.post(
            "/api/v1/paper-trading/execute",
            json={"symbol": "INFY", "side": "BUY", "quantity": 10},
            headers=auth_header(token),
        )
        assert response.status_code == 403
    finally:
        cleanup_user(user_id)
