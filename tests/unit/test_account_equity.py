"""src/engine/paper_trading/account_equity.py::compute_equity_from_positions unit tests
(REL-034) -- pure function, no DB, no broker. The async `compute_account_equity` orchestrator
is exercised indirectly via the paper-trading API integration tests once Stage 5's report
endpoints exist; this covers the actual arithmetic in isolation.
"""

from src.engine.paper_trading.account_equity import compute_equity_from_positions
from src.engine.paper_trading.position_accounting import SymbolPosition


def test_flat_account_equity_equals_capital_allocated():
    equity = compute_equity_from_positions(
        capital_allocated=100_000.0, positions={}, last_prices={}
    )
    assert equity == 100_000.0


def test_realized_pnl_adds_directly_to_equity():
    positions = {
        "INFY": SymbolPosition(
            symbol="INFY", net_quantity=0, realized_pnl=5_000.0, instrument_type="EQUITY"
        )
    }
    equity = compute_equity_from_positions(
        capital_allocated=100_000.0, positions=positions, last_prices={}
    )
    assert equity == 105_000.0


def test_unrealized_pnl_marks_open_long_position_to_the_live_quote():
    positions = {
        "INFY": SymbolPosition(
            symbol="INFY",
            net_quantity=100,
            average_cost=1500.0,
            instrument_type="EQUITY",
        )
    }
    # Marked up 10 points on 100 shares = +1000 unrealized, 0 margin (equity trade).
    equity = compute_equity_from_positions(
        capital_allocated=100_000.0, positions=positions, last_prices={"INFY": 1510.0}
    )
    assert equity == 101_000.0


def test_futures_margin_blocked_reduces_equity():
    positions = {
        "NIFTY24AUGFUT": SymbolPosition(
            symbol="NIFTY24AUGFUT",
            net_quantity=50,
            average_cost=24000.0,
            instrument_type="FUTURE",
        )
    }
    # No price move (average_cost == last_price -> 0 unrealized), but margin is still blocked.
    equity = compute_equity_from_positions(
        capital_allocated=100_000.0, positions=positions, last_prices={"NIFTY24AUGFUT": 24000.0}
    )
    notional = 50 * 24000.0
    assert equity == 100_000.0 - (notional * 0.18)


def test_missing_last_price_excludes_that_symbol_from_unrealized_and_margin_not_from_realized():
    positions = {
        "INFY": SymbolPosition(
            symbol="INFY",
            net_quantity=100,
            average_cost=1500.0,
            realized_pnl=2_000.0,
            instrument_type="EQUITY",
        )
    }
    # No quote for INFY -- unrealized/margin for it are honestly skipped, but its already-real
    # realized P&L still counts.
    equity = compute_equity_from_positions(
        capital_allocated=100_000.0, positions=positions, last_prices={}
    )
    assert equity == 102_000.0
