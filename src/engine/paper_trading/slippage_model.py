"""Depth-weighted fill simulation (Phase 4 Epic E4.4), per Phase_6_Trading_Engine_Design.md §5:
"Applies aggressive slippage assumptions and partial fill probabilities based on real-time order
book depth (Level 2 data) to simulate realistic market impact."

`simulate_fill()` is a pure function: it walks a REAL depth snapshot (fetched live from a broker
via BrokerAdapter.get_quote(), see src/brokers/base.py's `Quote`) level by level, exactly as a
real order would consume visible liquidity, rather than assuming the full requested quantity
fills instantly at one price. A market order that requests more quantity than the 5 visible
depth levels can absorb (the real limit of what Zerodha/Upstox report) is honestly reported as
partially filled -- never silently topped up with a fabricated price for the remainder.
"""

from dataclasses import dataclass

from src.brokers.base import DepthLevel, Side


@dataclass(frozen=True)
class FillResult:
    filled_quantity: int
    average_fill_price: float | None  # None only when filled_quantity == 0 (no depth at all)
    slippage_bps: float | None
    fully_filled: bool


def simulate_fill(*, side: Side, quantity: int, depth: list[DepthLevel]) -> FillResult:
    """A BUY consumes the sell (ask) side of the book -- you buy from whoever is offering to
    sell. A SELL consumes the buy (bid) side -- you sell to whoever is offering to buy. Callers
    pass the correct side's depth list (Quote.sell_depth for a BUY, Quote.buy_depth for a SELL);
    this function doesn't know about Quote's two-sided shape, only "the depth to walk"."""
    if quantity <= 0:
        raise ValueError(f"quantity must be positive, got {quantity}")
    if not depth:
        return FillResult(
            filled_quantity=0, average_fill_price=None, slippage_bps=None, fully_filled=False
        )

    touch_price: float | None = None  # the first genuinely quoted level -- the "fair" price
    # before market impact. NOT blindly depth[0]: a thin book (e.g. no bid interest) is reported
    # by both brokers as a zero-price/zero-quantity placeholder level, not an omitted one (see
    # the real Kite Connect example in this module's own tests) -- using it as the touch price
    # would divide by zero below.
    remaining = quantity
    total_cost = 0.0
    filled = 0

    for level in depth:
        if remaining <= 0:
            break
        if level.quantity <= 0 or level.price <= 0:
            continue  # a broker reporting an empty level (e.g. thin book) -- nothing to consume
        if touch_price is None:
            touch_price = level.price
        take = min(remaining, level.quantity)
        total_cost += take * level.price
        filled += take
        remaining -= take

    if filled == 0 or touch_price is None:
        return FillResult(
            filled_quantity=0, average_fill_price=None, slippage_bps=None, fully_filled=False
        )

    average_fill_price = total_cost / filled
    # Slippage is always reported as a market-impact *cost*, regardless of side: paying more than
    # touch price on a BUY, or receiving less than touch price on a SELL, is a real cost either way.
    if side == "BUY":
        slippage_bps = (average_fill_price - touch_price) / touch_price * 10_000
    else:
        slippage_bps = (touch_price - average_fill_price) / touch_price * 10_000

    return FillResult(
        filled_quantity=filled,
        average_fill_price=average_fill_price,
        # depth is sorted best-to-worst; never negative in practice
        slippage_bps=max(slippage_bps, 0.0),
        fully_filled=filled == quantity,
    )
