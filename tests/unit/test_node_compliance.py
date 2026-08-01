from unittest.mock import MagicMock, patch

import pytest

from src.agents.nodes.compliance import compliance_node
from src.agents.state import PythonCode, StrategyLogic, StrategyOptionLeg, TradingOSGraphState

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
_CODE = PythonCode(code="def run_backtest(data, config):\n    return {}\n", version_no=1)

_FO_STRATEGY_WITH_NAKED_LEG = _STRATEGY.model_copy(
    update={
        "asset_class": "F&O",
        "option_legs": [
            StrategyOptionLeg(
                symbol="NIFTY", option_type="CE", strike=25000, side="sell", quantity=50
            )
        ],
    }
)


def _fake_response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices[0].message.content = content
    return response


def _state():
    return TradingOSGraphState(thread_id="t1", strategy_logic=_STRATEGY, python_code=_CODE)


def test_compliance_node_requires_python_code():
    with pytest.raises(ValueError):
        compliance_node(TradingOSGraphState(thread_id="t1", strategy_logic=_STRATEGY))


def test_compliance_node_passes_a_clean_equity_strategy():
    narrative_json = '{"narrative": "No violations found."}'
    with patch("src.agents.nodes.compliance.complete", return_value=_fake_response(narrative_json)):
        result = compliance_node(_state())

    verdict = result["compliance_verdict"]
    assert verdict.verdict == "Pass"
    assert verdict.position_limit_checked is False  # no real order quantity at this stage
    assert verdict.naked_options_checked is False  # no structured leg data at this stage
    assert verdict.narrative == "No violations found."


def test_compliance_node_falls_back_to_deterministic_narrative_on_llm_failure():
    with patch("src.agents.nodes.compliance.complete", side_effect=RuntimeError("LLM down")):
        result = compliance_node(_state())

    verdict = result["compliance_verdict"]
    assert verdict.verdict == "Pass"
    assert "not run" in verdict.narrative


def test_compliance_node_blocks_a_real_naked_leg_declared_on_an_fo_strategy():
    """REL-016 E16.3 (GLH-09): this node's real veto power. A genuinely naked declared leg must
    produce verdict="Block", not just an advisory narrative -- the hardcoded compliance checker
    (src/engine/risk/compliance_checker.py) retains final authority here."""
    state = TradingOSGraphState(
        thread_id="t1", strategy_logic=_FO_STRATEGY_WITH_NAKED_LEG, python_code=_CODE
    )
    with patch("src.agents.nodes.compliance.complete", side_effect=RuntimeError("LLM down")):
        result = compliance_node(state)

    verdict = result["compliance_verdict"]
    assert verdict.verdict == "Block"
    assert verdict.naked_options_checked is True
    assert any("BR-02_NAKED_OPTIONS" in v for v in verdict.violations)
