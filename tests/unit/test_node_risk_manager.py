from unittest.mock import MagicMock, patch

import pytest

from src.agents.nodes.risk_manager import risk_manager_node
from src.agents.state import OptimizationResult, StrategyLogic, TradingOSGraphState

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


def _fake_response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices[0].message.content = content
    return response


def _state(optimization_passed=True):
    return TradingOSGraphState(
        thread_id="t1",
        strategy_logic=_STRATEGY,
        optimization_result=OptimizationResult(passed=optimization_passed),
    )


def test_risk_manager_node_requires_passed_optimization_result():
    with pytest.raises(ValueError):
        risk_manager_node(_state(optimization_passed=False))


def test_risk_manager_node_rejects_immediately_when_kill_switch_tripped():
    with (
        patch("src.agents.nodes.risk_manager.kill_switch_service.is_tripped", return_value=True),
        patch("src.agents.nodes.risk_manager.complete") as mock_complete,
    ):
        result = risk_manager_node(_state())

    assessment = result["risk_assessment"]
    assert assessment.decision == "Reject"
    assert assessment.kill_switch_tripped is True
    mock_complete.assert_not_called()


def test_risk_manager_node_approves_with_restrictions_when_armed():
    narrative_json = '{"narrative": "Kill switch armed, proceed with caution."}'
    with (
        patch("src.agents.nodes.risk_manager.kill_switch_service.is_tripped", return_value=False),
        patch(
            "src.agents.nodes.risk_manager.complete",
            return_value=_fake_response(narrative_json),
        ),
    ):
        result = risk_manager_node(_state())

    assessment = result["risk_assessment"]
    assert assessment.decision == "ApproveWithRestrictions"
    assert assessment.kill_switch_tripped is False
    assert assessment.correlation_passed is None
    assert assessment.naked_options_checked is False
    assert assessment.narrative == "Kill switch armed, proceed with caution."


def test_risk_manager_node_falls_back_to_deterministic_narrative_on_llm_failure():
    with (
        patch("src.agents.nodes.risk_manager.kill_switch_service.is_tripped", return_value=False),
        patch("src.agents.nodes.risk_manager.complete", side_effect=RuntimeError("LLM down")),
    ):
        result = risk_manager_node(_state())

    assert "not run" in result["risk_assessment"].narrative
