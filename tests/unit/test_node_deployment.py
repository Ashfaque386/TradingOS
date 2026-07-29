from unittest.mock import MagicMock, patch

import pytest

from src.agents.nodes.deployment import deployment_node
from src.agents.state import OptimizationResult, RiskAssessment, StrategyLogic, TradingOSGraphState

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


def _state(decision="ApproveWithRestrictions"):
    return TradingOSGraphState(
        thread_id="t1",
        strategy_logic=_STRATEGY,
        optimization_result=OptimizationResult(passed=True, notes="robust"),
        risk_assessment=RiskAssessment(
            decision=decision,
            kill_switch_tripped=(decision == "Reject"),
            naked_options_checked=False,
            narrative="narrative text",
        ),
    )


def test_deployment_node_requires_risk_assessment():
    with pytest.raises(ValueError):
        deployment_node(TradingOSGraphState(thread_id="t1"))


def test_deployment_node_recommends_paper_trading_on_approval():
    with patch(
        "src.agents.nodes.deployment.complete",
        return_value=_fake_response('{"rationale": "Looks solid."}'),
    ) as mock_complete:
        result = deployment_node(_state())

    rec = result["deployment_recommendation"]
    assert rec.recommended_status == "PaperTrading"
    assert rec.rationale == "Looks solid."
    assert mock_complete.call_args.args[0] == "research"


def test_deployment_node_recommends_reject_when_risk_rejected():
    with patch(
        "src.agents.nodes.deployment.complete",
        return_value=_fake_response('{"rationale": "Kill switch was tripped."}'),
    ):
        result = deployment_node(_state(decision="Reject"))

    rec = result["deployment_recommendation"]
    assert rec.recommended_status == "Reject"
    assert rec.rationale == "Kill switch was tripped."


def test_deployment_node_falls_back_to_deterministic_rationale_on_llm_failure():
    with patch("src.agents.nodes.deployment.complete", side_effect=RuntimeError("LLM down")):
        result = deployment_node(_state())

    rec = result["deployment_recommendation"]
    assert "Recommending PaperTrading" in rec.rationale
