"""Average-cost-basis position accounting over the Paper Trading ledger (Phase 4 Epic E4.4).

Shared by src/api/routers/paper_trading.py's /positions rollup and
src/engine/go_live_gate.py's Go-Live Readiness Gate (Phase_14_Master_Development_Roadmap.md
§5.4, condition 4: live-vs-backtest performance divergence), so both compute realized PnL --
and which individual trades closed a position -- the exact same way rather than risking two
implementations silently drifting apart. Average-cost-basis, not FIFO lot matching: each
closing trade realizes PnL against the position's running weighted-average entry price, a real,
standard, but simplified accounting choice.
"""

from dataclasses import dataclass

from src.models.paper_trading import PaperTrade


@dataclass
class SymbolPosition:
    symbol: str
    net_quantity: int = 0
    average_cost: float = 0.0
    realized_pnl: float = 0.0
    trade_count: int = 0
    # REL-034: a given `symbol` string always carries exactly one instrument type by
    # construction (an option's own broker trading symbol already encodes its strike/expiry/
    # type) -- set from the first trade seen for this symbol, never re-derived per fill.
    instrument_type: str = "EQUITY"


@dataclass(frozen=True)
class RealizedClose:
    """One position-reducing (or -reversing) fill -- the unit condition 4 of the Go-Live
    Readiness Gate counts wins/losses over, since it's the closest real analogue to a
    "round-trip trade" this average-cost ledger can produce without FIFO lot matching."""

    symbol: str
    quantity: int
    entry_price: float
    exit_price: float
    pnl: float


def replay_ledger(
    trades: list[PaperTrade],
) -> tuple[dict[str, SymbolPosition], list[RealizedClose]]:
    """Trades must already be ordered by executed_at ascending -- the caller's query, not this
    function, owns ordering, since a session/query is a router/gate concern, not an accounting
    one."""
    positions: dict[str, SymbolPosition] = {}
    closes: list[RealizedClose] = []

    for t in trades:
        pos = positions.setdefault(
            t.symbol, SymbolPosition(symbol=t.symbol, instrument_type=t.instrument_type)
        )
        pos.trade_count += 1
        signed_qty = t.filled_quantity if t.side == "BUY" else -t.filled_quantity
        fill_price = float(t.fill_price)

        if pos.net_quantity == 0 or (pos.net_quantity > 0) == (signed_qty > 0):
            # Opening or adding to a position in the same direction: extend the weighted
            # average cost basis.
            new_qty = pos.net_quantity + signed_qty
            if new_qty != 0:
                pos.average_cost = (
                    pos.average_cost * abs(pos.net_quantity) + fill_price * abs(signed_qty)
                ) / abs(new_qty)
            pos.net_quantity = new_qty
        else:
            # Reducing or reversing: realize PnL on the closed portion against the current
            # average cost.
            closing_qty = min(abs(signed_qty), abs(pos.net_quantity))
            direction = 1 if pos.net_quantity > 0 else -1
            pnl = direction * (fill_price - pos.average_cost) * closing_qty
            pos.realized_pnl += pnl
            closes.append(
                RealizedClose(
                    symbol=t.symbol,
                    quantity=closing_qty,
                    entry_price=pos.average_cost,
                    exit_price=fill_price,
                    pnl=pnl,
                )
            )
            pos.net_quantity += signed_qty
            reversed_through_zero = (pos.net_quantity > 0) != (pos.net_quantity - signed_qty > 0)
            if pos.net_quantity != 0 and reversed_through_zero:
                # Reversed through zero into the opposite side -- the remainder opens a new
                # position at this fill's price.
                pos.average_cost = fill_price

    return positions, closes
