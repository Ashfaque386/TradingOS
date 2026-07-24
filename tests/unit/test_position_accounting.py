"""src/engine/paper_trading/position_accounting.py unit tests (Phase 4 Epic E4.4) -- pure
function, no DB, no broker. Mirrors the values already verified against the real API in
tests/integration/test_paper_trading_api.py::test_positions_computes_average_cost_basis_and_realized_pnl,
plus the RealizedClose events that test doesn't check (they only matter to the Go-Live
Readiness Gate's win-rate condition, not the /positions endpoint).
"""

from datetime import UTC, datetime

from src.engine.paper_trading.position_accounting import replay_ledger
from src.models.paper_trading import PaperTrade


def _trade(*, symbol: str, side: str, qty: int, price: float) -> PaperTrade:
    return PaperTrade(
        strategy_id=None,
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


def test_two_buys_then_a_partial_sell_computes_weighted_average_cost_and_one_realized_close():
    trades = [
        _trade(symbol="INFY", side="BUY", qty=100, price=50.00),
        _trade(symbol="INFY", side="BUY", qty=100, price=52.00),
        _trade(symbol="INFY", side="SELL", qty=150, price=55.00),
    ]

    positions, closes = replay_ledger(trades)

    position = positions["INFY"]
    assert position.net_quantity == 50
    assert position.average_cost == 51.00
    assert position.realized_pnl == 600.00
    assert position.trade_count == 3

    assert len(closes) == 1
    assert closes[0].quantity == 150
    assert closes[0].entry_price == 51.00
    assert closes[0].exit_price == 55.00
    assert closes[0].pnl == 600.00


def test_a_losing_close_is_recorded_with_negative_pnl():
    trades = [
        _trade(symbol="TCS", side="BUY", qty=10, price=100.0),
        _trade(symbol="TCS", side="SELL", qty=10, price=90.0),
    ]

    _, closes = replay_ledger(trades)

    assert len(closes) == 1
    assert closes[0].pnl == -100.0


def test_reversing_through_zero_opens_a_new_position_at_the_reversing_fill_price():
    trades = [
        _trade(symbol="RELIANCE", side="BUY", qty=10, price=100.0),
        _trade(symbol="RELIANCE", side="SELL", qty=25, price=110.0),  # closes 10, opens -15 short
    ]

    positions, closes = replay_ledger(trades)

    position = positions["RELIANCE"]
    assert position.net_quantity == -15
    assert position.average_cost == 110.0  # the reversing fill's price, not the old long's cost
    assert len(closes) == 1
    assert closes[0].quantity == 10
    assert closes[0].pnl == 100.0


def test_a_short_side_open_position_is_never_realized():
    trades = [_trade(symbol="HDFC", side="SELL", qty=10, price=100.0)]

    positions, closes = replay_ledger(trades)

    assert positions["HDFC"].net_quantity == -10
    assert positions["HDFC"].realized_pnl == 0.0
    assert closes == []
