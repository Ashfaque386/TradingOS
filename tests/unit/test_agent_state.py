import pytest
from pydantic import ValidationError

from src.agents.state import (
    BacktestMetrics,
    EvaluationVerdict,
    MarketContext,
    PythonCode,
    ResearchDirective,
    StrategyLogic,
    TradingOSGraphState,
    ValidationResult,
)


def test_research_directive_accepts_valid_payload():
    directive = ResearchDirective(
        market_regime="Bullish",
        priority_sectors=["IT", "Banking"],
        strategy_themes=["Momentum"],
        risk_tolerance="Medium",
        participating_agents=["MarketAnalystAgent", "StrategyGeneratorAgent"],
        expected_outcomes="Identify 2-3 momentum strategies in IT/Banking",
    )
    assert directive.is_fallback_directive is False


def test_research_directive_rejects_invalid_market_regime():
    with pytest.raises(ValidationError):
        ResearchDirective(
            market_regime="Extremely Bullish",  # not in the allowed Literal set
            priority_sectors=["IT"],
            strategy_themes=["Momentum"],
            risk_tolerance="Medium",
            participating_agents=["MarketAnalystAgent"],
            expected_outcomes="x",
        )


def test_research_directive_rejects_unknown_field():
    with pytest.raises(ValidationError):
        ResearchDirective(
            market_regime="Bullish",
            priority_sectors=["IT"],
            strategy_themes=["Momentum"],
            risk_tolerance="Medium",
            participating_agents=["MarketAnalystAgent"],
            expected_outcomes="x",
            some_unexpected_field="should be rejected",
        )


def test_market_context_rejects_out_of_range_confidence_score():
    with pytest.raises(ValidationError):
        MarketContext(
            market_regime="Sideways",
            sector_rankings=["IT", "Pharma"],
            volatility_assessment="Low",
            macro_outlook="Stable",
            confidence_score=1.5,  # out of [0, 1] range
            insights=["Range-bound market"],
        )


def test_strategy_logic_rejects_invalid_asset_class():
    with pytest.raises(ValidationError):
        StrategyLogic(
            hypothesis="Mean reversion on Nifty Bank",
            asset_class="Commodities",  # not Equity/F&O
            style="Intraday",
            universe=["BANKNIFTY"],
            entry_conditions="RSI < 30",
            exit_conditions="RSI > 70",
            stop_loss="2%",
            take_profit="4%",
            position_sizing="1% risk per trade",
            confidence_score=0.7,
        )


def test_python_code_defaults_version_to_1():
    code = PythonCode(code="def run_backtest(data, config): ...")
    assert code.version_no == 1


def test_validation_result_status_must_be_pass_or_fail():
    with pytest.raises(ValidationError):
        ValidationResult(status="Maybe")


def test_backtest_metrics_requires_sharpe_and_max_drawdown():
    with pytest.raises(ValidationError):
        BacktestMetrics(sortino_ratio=1.2)  # missing required sharpe_ratio/max_drawdown


def test_evaluation_verdict_defaults_to_empty_failure_reasons():
    verdict = EvaluationVerdict(verdict="PASS")
    assert verdict.failure_reasons == []


def test_graph_state_starts_with_zeroed_counters():
    state = TradingOSGraphState(thread_id="thread-1")
    assert state.code_validation_retry_count == 0
    assert state.strategy_rejection_count == 0
    assert state.research_directive is None


def test_graph_state_rejects_malformed_nested_object():
    with pytest.raises(ValidationError):
        TradingOSGraphState(
            thread_id="thread-1",
            research_directive={"market_regime": "NotARealRegime"},
        )
