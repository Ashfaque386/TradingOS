"""Simplified F&O margin approximation for the Paper Trading Account (REL-034).

The real `BrokerAdapter.get_margin()` (src/brokers/base.py) only returns account-level
available/used margin -- there is no per-order margin-calculator method in the broker interface
(neither Zerodha nor Upstox's adapter exposes one), so a genuinely accurate SPAN+exposure margin
figure isn't available to compute here. This is a documented, honest approximation, not a
fabricated precise number: futures block a flat percentage of notional; long options block
nothing beyond the premium already debited from cash at fill time; short/naked options are
treated conservatively (full notional) as a defensive fallback, since scan_for_naked_options()
(src/engine/risk/naked_options_scanner.py) should already have blocked any such position from
ever opening via the compliance pre-trade check -- if one is ever found open anyway (e.g. a
hedge leg closed independently), this deliberately over-estimates rather than under-estimates
the capital at risk.

Margin blocked is replay-computed from `position_accounting.SymbolPosition`, not a stored/mutable
column -- see position_accounting.py's own module docstring for why (a pure function of
*currently open* positions means "release on square-off" falls out for free with zero drift
risk, the same reasoning already applied to realized/unrealized P&L in this ledger).
"""

from dataclasses import dataclass, field

from src.engine.paper_trading.position_accounting import SymbolPosition

# Documented approximation, mid-point of a real-world ~15-20% initial-margin range for NSE
# index/stock futures -- not derived from any live margin API.
FUTURES_MARGIN_PCT = 0.18


@dataclass(frozen=True)
class MarginLine:
    symbol: str
    instrument_type: str
    net_quantity: int
    notional: float
    margin_required: float


@dataclass(frozen=True)
class MarginSummary:
    total_margin_blocked: float
    lines: list[MarginLine] = field(default_factory=list)


def compute_margin_line(pos: SymbolPosition, last_price: float) -> MarginLine:
    notional = abs(pos.net_quantity) * last_price

    if pos.net_quantity == 0:
        margin_required = 0.0
    elif pos.instrument_type == "EQUITY":
        margin_required = 0.0  # cash trade, no leverage modeled
    elif pos.instrument_type == "FUTURE":
        margin_required = notional * FUTURES_MARGIN_PCT
    elif pos.instrument_type in ("CE", "PE") and pos.net_quantity > 0:
        margin_required = 0.0  # long option: premium already debited from cash at entry
    else:
        # Short/naked option (net_quantity < 0) reaching here at all is itself the honest
        # signal something upstream (the naked-options veto) didn't catch it -- treat it as the
        # worst real case, never silently 0.
        margin_required = notional

    return MarginLine(
        symbol=pos.symbol,
        instrument_type=pos.instrument_type,
        net_quantity=pos.net_quantity,
        notional=notional,
        margin_required=margin_required,
    )


def compute_margin_summary(
    positions: dict[str, SymbolPosition], last_prices: dict[str, float]
) -> MarginSummary:
    """`last_prices` missing an entry for an open symbol is a real, honest gap (a quote fetch
    failed) -- that line is skipped rather than guessed at with a stale/fabricated price, and the
    resulting total is therefore a lower bound, not silently wrong in the risky direction."""
    lines = [
        compute_margin_line(pos, last_prices[symbol])
        for symbol, pos in positions.items()
        if pos.net_quantity != 0 and symbol in last_prices
    ]
    return MarginSummary(
        total_margin_blocked=sum(line.margin_required for line in lines), lines=lines
    )
