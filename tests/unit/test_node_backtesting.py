from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.agents.nodes.backtesting import backtesting_node
from src.agents.state import PythonCode, StrategyLogic, TradingOSGraphState
from src.engine.sandbox.backtest_runner import RealBacktestOutcome

_STRATEGY = StrategyLogic(
    hypothesis="momentum",
    asset_class="Equity",
    style="Swing",
    universe=["RELIANCE"],
    entry_conditions="close > sma_20",
    exit_conditions="close < sma_20",
    stop_loss="2%",
    take_profit="5%",
    position_sizing="fixed",
    confidence_score=0.7,
)
_CODE = PythonCode(code="def run_backtest(data, config): return {}")


def _state(**overrides):
    defaults = {"thread_id": "t1", "strategy_logic": _STRATEGY, "python_code": _CODE}
    defaults.update(overrides)
    return TradingOSGraphState(**defaults)


def test_backtesting_node_requires_python_code():
    with pytest.raises(ValueError):
        backtesting_node(TradingOSGraphState(thread_id="t1", strategy_logic=_STRATEGY))


def test_backtesting_node_requires_universe():
    empty_universe_strategy = _STRATEGY.model_copy(update={"universe": []})
    with pytest.raises(ValueError):
        backtesting_node(_state(strategy_logic=empty_universe_strategy))


def _patched(outcome=None, latest_date=date(2024, 7, 19)):
    outcome = outcome or RealBacktestOutcome(
        passed=True,
        error=None,
        symbol_used="RELIANCE",
        metrics={"sharpe_ratio": 1.8, "max_drawdown": -0.12, "total_trades": 42},
    )
    lake_instance = MagicMock()
    lake_instance.latest_date.return_value = latest_date
    return (
        patch("src.agents.nodes.backtesting.require_fresh"),
        patch("src.agents.nodes.backtesting.DataLake", return_value=lake_instance),
        patch("src.agents.nodes.backtesting.run_real_backtest", return_value=outcome),
    )


def test_backtesting_node_produces_backtest_metrics_from_a_real_outcome():
    fresh, lake, run = _patched()
    with fresh, lake, run as mock_run:
        result = backtesting_node(_state())

    metrics = result["backtest_metrics"]
    assert metrics.sharpe_ratio == 1.8
    assert metrics.max_drawdown == -0.12
    assert metrics.total_trades == 42
    assert mock_run.call_args.kwargs["universe"] == ["RELIANCE"]


def test_backtesting_node_raises_when_no_data_ingested():
    fresh, lake, run = _patched(latest_date=None)
    with fresh, lake, run, pytest.raises(ValueError, match="No historical data ingested"):
        backtesting_node(_state())


def test_backtesting_node_raises_when_real_backtest_fails():
    failed_outcome = RealBacktestOutcome(
        passed=False, error="ZeroDivisionError", symbol_used="RELIANCE"
    )
    fresh, lake, run = _patched(outcome=failed_outcome)
    with fresh, lake, run, pytest.raises(ValueError, match="ZeroDivisionError"):
        backtesting_node(_state())


def test_backtesting_node_checks_freshness_against_real_wall_clock_today():
    fresh, lake, run = _patched()
    with fresh as mock_fresh, lake, run:
        backtesting_node(_state())

    assert mock_fresh.call_args.kwargs["as_of"] == date.today()
