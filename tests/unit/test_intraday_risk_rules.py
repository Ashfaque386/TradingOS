"""src/engine/paper_trading/intraday_risk_rules.py unit tests (REL-034) -- pure closure, no DB,
no broker. Confirms the core correctness property: more than one trade per real trading day for
the same position (stop-loss exit, then a real re-entry once price recovers), the exact behavior
you corrected an earlier draft of this plan to require.
"""

from datetime import UTC, datetime

from src.engine.live.execution_pipeline import SymbolState, Tick
from src.engine.paper_trading.intraday_risk_rules import build_stop_loss_signal_generator


def _tick(price: float) -> Tick:
    return Tick(symbol="INFY", price=price, timestamp=datetime.now(UTC))


def test_no_signal_while_price_stays_within_the_drawdown_limit():
    state = SymbolState(symbol="INFY")
    generator = build_stop_loss_signal_generator(
        symbol="INFY", quantity=10, entry_price=100.0, max_drawdown_limit_pct=15.0
    )

    for price in (100.0, 98.0, 90.0, 86.0):  # worst case here is 14% loss, under the 15% limit
        state.update(price)
        assert generator(state) is None


def test_stop_loss_fires_a_sell_once_the_drawdown_limit_is_breached():
    state = SymbolState(symbol="INFY")
    generator = build_stop_loss_signal_generator(
        symbol="INFY", quantity=10, entry_price=100.0, max_drawdown_limit_pct=15.0
    )

    state.update(100.0)
    assert generator(state) is None

    state.update(84.0)  # 16% loss -- breaches the 15% limit
    signal = generator(state)

    assert signal is not None
    assert signal.side == "SELL"
    assert signal.quantity == 10
    assert signal.symbol == "INFY"


def test_no_further_signal_while_flat_and_price_stays_below_the_original_entry():
    state = SymbolState(symbol="INFY")
    generator = build_stop_loss_signal_generator(
        symbol="INFY", quantity=10, entry_price=100.0, max_drawdown_limit_pct=15.0
    )
    state.update(100.0)
    state.update(84.0)
    generator(state)  # stops out, now flat

    state.update(90.0)  # recovering, but still below the original entry of 100.0
    assert generator(state) is None


def test_re_entry_fires_a_buy_once_price_recovers_to_the_original_entry():
    state = SymbolState(symbol="INFY")
    generator = build_stop_loss_signal_generator(
        symbol="INFY", quantity=10, entry_price=100.0, max_drawdown_limit_pct=15.0
    )
    state.update(100.0)
    state.update(84.0)
    generator(state)  # stops out, now flat

    state.update(101.0)  # recovered above the original entry
    signal = generator(state)

    assert signal is not None
    assert signal.side == "BUY"
    assert signal.quantity == 10


def test_a_full_stop_loss_then_re_entry_then_stop_loss_cycle_is_multiple_real_trades():
    """The exact scenario the plan's Architecture section names explicitly: more than one trade
    in a single day for one strategy, driven by real intraday price action."""
    state = SymbolState(symbol="INFY")
    generator = build_stop_loss_signal_generator(
        symbol="INFY", quantity=10, entry_price=100.0, max_drawdown_limit_pct=15.0
    )
    signals = []

    for price in (100.0, 84.0, 101.0, 85.0):
        state.update(price)
        signal = generator(state)
        if signal is not None:
            signals.append(signal)

    assert [s.side for s in signals] == ["SELL", "BUY", "SELL"]
