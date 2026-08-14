"""src/agents/nodes/compliance.py's `_latest_close_price`/`_estimate_conservative_quantity`
against the real ingested `^NSEI` (Nifty 50) Parquet data in the data lake -- no mocking, matching
this codebase's convention of testing real local infrastructure directly (same real data source
tests/integration/test_risk_manager_correlation_real_data.py already relies on)."""

from src.agents.nodes.compliance import _estimate_conservative_quantity, _latest_close_price
from src.agents.state import StrategyLogic, TradingOSGraphState

_STRATEGY = StrategyLogic(
    hypothesis="index tracker",
    asset_class="Equity",
    style="Swing",
    universe=["^NSEI"],
    entry_conditions="close > sma_20",
    exit_conditions="close < sma_20",
    stop_loss="2%",
    take_profit="5%",
    position_sizing="fixed",
    confidence_score=0.7,
)


def test_latest_close_price_returns_a_real_positive_price_for_an_ingested_symbol() -> None:
    price = _latest_close_price("^NSEI")
    assert price is not None
    assert price > 0


def test_latest_close_price_is_honestly_none_for_a_never_ingested_symbol() -> None:
    price = _latest_close_price("__NOT_A_REAL_SYMBOL__")
    assert price is None


def test_estimate_conservative_quantity_uses_the_real_latest_price() -> None:
    state = TradingOSGraphState(
        thread_id="t1", strategy_logic=_STRATEGY, account_capital=1_000_000.0
    )
    quantity = _estimate_conservative_quantity(state, "^NSEI")
    price = _latest_close_price("^NSEI")

    assert quantity is not None
    assert price is not None
    assert quantity == int(1_000_000.0 // price)
    assert quantity > 0


def test_estimate_conservative_quantity_is_honestly_none_without_account_capital() -> None:
    state = TradingOSGraphState(thread_id="t1", strategy_logic=_STRATEGY, account_capital=None)
    assert _estimate_conservative_quantity(state, "^NSEI") is None
