from unittest.mock import MagicMock, patch

import pytest

from src.agents.nodes.compliance import compliance_node
from src.agents.state import PythonCode, StrategyLogic, TradingOSGraphState

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
