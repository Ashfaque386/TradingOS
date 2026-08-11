"""Layer 2's actual per-tick decision rule (REL-034): a universal stop-loss/re-entry
`SignalGenerator`, deliberately NOT a reinterpretation of the strategy's own vectorbt signal
logic. Re-running that logic at tick/bar granularity would silently change what a daily-bar-
validated strategy's indicators mean (see daily_signal_job.py's own module docstring for the
full reasoning) -- this rule instead only ever compares the live price to two universal,
always-valid numbers: the position's own entry price and the strategy's own hardcoded
`max_drawdown_limit`, the same field Phase_6_Trading_Engine_Design.md §4 already uses as a
portfolio-level hard stop, applied here at the single-position level.

Genuinely supports more than one trade per real trading day for the same strategy, per your own
explicit correction to an earlier draft of this plan: this closure tracks its own open/flat
state across ticks, firing a real SELL on a stop-loss breach and a real re-entry BUY once price
recovers back to (or above) the original entry -- both real transitions, not capped at a single
decision point."""

from dataclasses import dataclass

from src.brokers.base import Side
from src.engine.live.execution_pipeline import SignalGenerator, SymbolState, TradeSignal


@dataclass
class _PositionState:
    symbol: str
    quantity: int
    entry_price: float
    max_drawdown_limit_pct: float
    is_open: bool = True


def build_stop_loss_signal_generator(
    *, symbol: str, quantity: int, entry_price: float, max_drawdown_limit_pct: float
) -> SignalGenerator:
    """Returns a `SignalGenerator` closure (src/engine/live/execution_pipeline.py's type alias)
    scoped to one open paper position. `max_drawdown_limit_pct` is the strategy's own
    `Strategy.max_drawdown_limit` field (e.g. `15.00` meaning 15%)."""
    pos = _PositionState(
        symbol=symbol,
        quantity=quantity,
        entry_price=entry_price,
        max_drawdown_limit_pct=max_drawdown_limit_pct,
    )

    def signal_generator(state: SymbolState) -> TradeSignal | None:
        if not state.prices:
            return None
        current_price = state.prices[-1]

        if pos.is_open:
            loss_pct = (pos.entry_price - current_price) / pos.entry_price * 100.0
            if loss_pct >= pos.max_drawdown_limit_pct:
                side: Side = "SELL"
                pos.is_open = False
                return TradeSignal(
                    symbol=pos.symbol,
                    side=side,
                    quantity=pos.quantity,
                    reference_price=current_price,
                )
            return None

        # Stopped out -- re-enter once price recovers back to (or above) the original entry,
        # an honest, explicitly-scoped re-entry rule (not a re-run of the strategy's own signal
        # logic, see module docstring).
        if current_price >= pos.entry_price:
            side = "BUY"
            pos.is_open = True
            pos.entry_price = current_price
            return TradeSignal(
                symbol=pos.symbol, side=side, quantity=pos.quantity, reference_price=current_price
            )
        return None

    return signal_generator
