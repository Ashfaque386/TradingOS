"""src/engine/paper_trading/margin_model.py unit tests (REL-034) -- pure function, no DB.

Covers the documented, simplified approximation directly: equity trades 0-margin, futures at
FUTURES_MARGIN_PCT of notional, long options 0-margin (premium already debited from cash), and
the defensive worst-case treatment of a short option position (should never occur in practice --
scan_for_naked_options() should already have blocked it -- but this margin model must not
silently under-report it as 0 if one is ever found open anyway).
"""

from src.engine.paper_trading.margin_model import (
    FUTURES_MARGIN_PCT,
    compute_margin_line,
    compute_margin_summary,
)
from src.engine.paper_trading.position_accounting import SymbolPosition


def test_equity_position_blocks_zero_margin():
    pos = SymbolPosition(symbol="INFY", net_quantity=100, instrument_type="EQUITY")
    line = compute_margin_line(pos, last_price=1500.0)
    assert line.notional == 150_000.0
    assert line.margin_required == 0.0


def test_future_position_blocks_the_documented_percentage_of_notional():
    pos = SymbolPosition(symbol="NIFTY24AUGFUT", net_quantity=50, instrument_type="FUTURE")
    line = compute_margin_line(pos, last_price=24000.0)
    assert line.notional == 1_200_000.0
    assert line.margin_required == 1_200_000.0 * FUTURES_MARGIN_PCT


def test_long_option_blocks_no_additional_margin():
    pos = SymbolPosition(symbol="NIFTY24AUG24000CE", net_quantity=50, instrument_type="CE")
    line = compute_margin_line(pos, last_price=150.0)
    assert line.margin_required == 0.0


def test_short_option_defensively_blocks_full_notional_not_zero():
    """Should never actually reach an open position (naked-options veto blocks it upstream) --
    this is the honest worst-case fallback, never a silent 0."""
    pos = SymbolPosition(symbol="NIFTY24AUG24000PE", net_quantity=-50, instrument_type="PE")
    line = compute_margin_line(pos, last_price=150.0)
    assert line.margin_required == line.notional
    assert line.margin_required > 0


def test_flat_position_blocks_zero_margin():
    pos = SymbolPosition(symbol="INFY", net_quantity=0, instrument_type="EQUITY")
    line = compute_margin_line(pos, last_price=1500.0)
    assert line.margin_required == 0.0


def test_summary_sums_across_open_positions_and_skips_missing_prices():
    positions = {
        "INFY": SymbolPosition(symbol="INFY", net_quantity=100, instrument_type="EQUITY"),
        "NIFTY24AUGFUT": SymbolPosition(
            symbol="NIFTY24AUGFUT", net_quantity=50, instrument_type="FUTURE"
        ),
        "FLAT": SymbolPosition(symbol="FLAT", net_quantity=0, instrument_type="EQUITY"),
        "NO_QUOTE": SymbolPosition(symbol="NO_QUOTE", net_quantity=10, instrument_type="EQUITY"),
    }
    last_prices = {"INFY": 1500.0, "NIFTY24AUGFUT": 24000.0}

    summary = compute_margin_summary(positions, last_prices)

    # FLAT excluded (net_quantity == 0), NO_QUOTE excluded (no price available) -- neither
    # fabricates a line.
    assert {line.symbol for line in summary.lines} == {"INFY", "NIFTY24AUGFUT"}
    assert summary.total_margin_blocked == 1_200_000.0 * FUTURES_MARGIN_PCT
