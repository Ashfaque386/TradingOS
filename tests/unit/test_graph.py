from unittest.mock import patch

from src.agents.state import (
    MarketContext,
    PythonCode,
    ResearchDirective,
    StrategyLogic,
    TradingOSGraphState,
    ValidationResult,
)

_DIRECTIVE = ResearchDirective(
    market_regime="Bullish",
    priority_sectors=["IT"],
    strategy_themes=["Momentum"],
    risk_tolerance="Medium",
    participating_agents=["MarketAnalystAgent"],
    expected_outcomes="Find momentum plays",
)
_CONTEXT = MarketContext(
    market_regime="Bullish",
    sector_rankings=["IT"],
    volatility_assessment="Low",
    macro_outlook="Stable",
    confidence_score=0.7,
    insights=["Momentum favorable"],
)
_STRATEGY = StrategyLogic(
    hypothesis="Momentum breakout",
    asset_class="Equity",
    style="Intraday",
    universe=["TCS"],
    entry_conditions="Breakout above 20-day high",
    exit_conditions="Close below 10-day low",
    stop_loss="2%",
    take_profit="5%",
    position_sizing="1% risk",
    confidence_score=0.8,
)
_CODE = PythonCode(code="def run_backtest(data, config):\n    return {}\n", version_no=1)


def _mock_pipeline(*, validator_side_effect):
    return (
        patch("src.agents.graph.ceo_agent_node", return_value={"research_directive": _DIRECTIVE}),
        patch("src.agents.graph.market_analyst_node", return_value={"market_context": _CONTEXT}),
        patch(
            "src.agents.graph.strategy_generator_node",
            return_value={"strategy_logic": _STRATEGY, "strategy_rejection_count": 0},
        ),
        patch(
            "src.agents.graph.python_code_generator_node",
            return_value={"python_code": _CODE},
        ),
        patch("src.agents.graph.python_validator_node", side_effect=validator_side_effect),
    )


def test_graph_happy_path_reaches_await_backtesting():
    def validator(state):
        return {
            "validation_result": ValidationResult(status="Pass"),
            "code_validation_retry_count": 0,
        }

    patches = _mock_pipeline(validator_side_effect=validator)
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        from src.agents.graph import build_graph

        result = build_graph().invoke(TradingOSGraphState(thread_id="t1"))

    assert result["validation_result"].status == "Pass"
    assert result["research_directive"].market_regime == "Bullish"


def test_graph_retries_validator_then_passes():
    call_count = {"n": 0}

    def validator(state):
        call_count["n"] += 1
        if call_count["n"] < 2:
            return {
                "validation_result": ValidationResult(status="Fail", feedback="bad code"),
                "code_validation_retry_count": state.code_validation_retry_count + 1,
            }
        return {
            "validation_result": ValidationResult(status="Pass"),
            "code_validation_retry_count": state.code_validation_retry_count,
        }

    patches = _mock_pipeline(validator_side_effect=validator)
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        from src.agents.graph import build_graph

        result = build_graph().invoke(TradingOSGraphState(thread_id="t1"))

    assert result["validation_result"].status == "Pass"
    assert call_count["n"] == 2


def test_graph_fails_gracefully_after_max_retries():
    def validator(state):
        return {
            "validation_result": ValidationResult(status="Fail", feedback="always bad"),
            "code_validation_retry_count": state.code_validation_retry_count + 1,
        }

    patches = _mock_pipeline(validator_side_effect=validator)
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        from src.agents.graph import build_graph

        result = build_graph().invoke(TradingOSGraphState(thread_id="t1"))

    assert result["validation_result"].status == "Fail"
    assert result["code_validation_retry_count"] == 3
