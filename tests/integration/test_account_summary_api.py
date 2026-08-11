"""GET /api/v1/paper-trading/account/{summary,equity-curve,statement/export} integration tests
(REL-034), against the real FastAPI app + real Postgres + the real seeded Paper account.
"""

import uuid
from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from src.api.main import app
from src.core.db import get_session
from src.engine.paper_trading.paper_account import get_paper_account
from src.models.account import AccountEquitySnapshot
from src.models.paper_trading import PaperTrade

client = TestClient(app)


def _seed_trade(
    *, symbol: str, side: str, qty: int, price: float, instrument_type="EQUITY"
) -> uuid.UUID:
    with get_session() as session:
        account_id = get_paper_account(session).id
        trade = PaperTrade(
            account_id=account_id,
            instrument_type=instrument_type,
            symbol=symbol,
            side=side,
            requested_quantity=qty,
            filled_quantity=qty,
            reference_price=price,
            fill_price=price,
            slippage_bps=0.0,
            depth_snapshot={},
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


def test_account_summary_reflects_starting_capital_when_no_trades_exist():
    response = client.get("/api/v1/paper-trading/account/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["starting_capital"] == 100000.0
    assert body["account_id"]


def test_account_summary_includes_realized_pnl_from_a_real_closed_position():
    symbol = f"TESTSYM{uuid.uuid4().hex[:6].upper()}"
    ids = [
        _seed_trade(symbol=symbol, side="BUY", qty=10, price=100.0),
        _seed_trade(symbol=symbol, side="SELL", qty=10, price=110.0),
    ]
    try:
        response = client.get("/api/v1/paper-trading/account/summary")
        assert response.status_code == 200
        body = response.json()
        # Realized P&L across the WHOLE account ledger includes every other test's trades too
        # (a shared account, same convention as GET /positions) -- assert this one round trip's
        # contribution is present, not an exact total.
        assert body["realized_pnl_total"] >= 100.0
        assert "EQUITY" in body["realized_pnl_by_instrument_class"]
    finally:
        _cleanup(*ids)


def test_account_equity_curve_always_includes_a_live_point_for_today():
    response = client.get("/api/v1/paper-trading/account/equity-curve")
    assert response.status_code == 200
    body = response.json()
    assert len(body) >= 1
    assert body[-1]["snapshot_date"] == date.today().isoformat()


def test_account_equity_curve_uses_a_real_snapshot_row_when_one_exists():
    with get_session() as session:
        account_id = get_paper_account(session).id
        snapshot = AccountEquitySnapshot(
            account_id=account_id,
            snapshot_date=date(2020, 1, 1),
            cash=100000.0,
            realized_pnl_cumulative=0.0,
            unrealized_pnl=0.0,
            margin_blocked=0.0,
            equity=100000.0,
        )
        session.add(snapshot)
        session.commit()
        snapshot_id = snapshot.id

    try:
        response = client.get(
            "/api/v1/paper-trading/account/equity-curve?from=2020-01-01&to=2020-01-01"
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["snapshot_date"] == "2020-01-01"
        assert body[0]["equity"] == 100000.0
    finally:
        with get_session() as session:
            session.query(AccountEquitySnapshot).filter(
                AccountEquitySnapshot.id == snapshot_id
            ).delete()
            session.commit()


def test_account_statement_export_csv_contains_a_real_seeded_trade():
    symbol = f"TESTSYM{uuid.uuid4().hex[:6].upper()}"
    trade_id = _seed_trade(symbol=symbol, side="BUY", qty=5, price=42.0)
    try:
        response = client.get("/api/v1/paper-trading/account/statement/export?format=csv")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert symbol in response.text
    finally:
        _cleanup(trade_id)


def test_account_statement_export_ndjson_contains_a_real_seeded_trade():
    symbol = f"TESTSYM{uuid.uuid4().hex[:6].upper()}"
    trade_id = _seed_trade(symbol=symbol, side="BUY", qty=5, price=42.0)
    try:
        response = client.get("/api/v1/paper-trading/account/statement/export?format=ndjson")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")
        assert symbol in response.text
    finally:
        _cleanup(trade_id)
