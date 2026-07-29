from unittest.mock import MagicMock, patch

from src.agents.nodes.ceo import ceo_agent_node
from src.agents.state import TradingOSGraphState


def _fake_response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices[0].message.content = content
    return response


def test_ceo_agent_node_parses_valid_directive():
    directive_json = (
        '{"market_regime": "Bullish", "priority_sectors": ["IT"], '
        '"strategy_themes": ["Momentum"], "risk_tolerance": "Medium", '
        '"participating_agents": ["MarketAnalystAgent"], '
        '"expected_outcomes": "Find momentum plays in IT"}'
    )
    with patch(
        "src.agents.nodes.ceo.complete", return_value=_fake_response(directive_json)
    ) as mock_complete:
        result = ceo_agent_node(TradingOSGraphState(thread_id="t1"))

    assert result["research_directive"].market_regime == "Bullish"
    assert result["research_directive"].is_fallback_directive is False
    assert mock_complete.call_args.args[0] == "orchestration"
    assert result["strategy_rejection_count"] == 0


def test_ceo_agent_node_falls_back_on_llm_failure():
    with patch("src.agents.nodes.ceo.complete", side_effect=RuntimeError("LLM down")):
        result = ceo_agent_node(TradingOSGraphState(thread_id="t1"))

    assert result["research_directive"].is_fallback_directive is True
    assert result["research_directive"].market_regime == "Sideways"


def test_ceo_agent_node_resets_rejection_count_on_escalated_reentry():
    """The 5-consecutive-rejection escalation (REL-005 E5.2) re-enters here; a fresh cycle with
    loosened constraints deserves a fresh 5-strikes budget, not an already-tripped counter."""
    escalated_state = TradingOSGraphState(thread_id="t1", strategy_rejection_count=5)
    with patch("src.agents.nodes.ceo.complete", side_effect=RuntimeError("LLM down")):
        result = ceo_agent_node(escalated_state)

    assert result["strategy_rejection_count"] == 0


def test_ceo_agent_node_falls_back_on_malformed_json():
    with patch(
        "src.agents.nodes.ceo.complete", return_value=_fake_response("not valid json at all")
    ):
        result = ceo_agent_node(TradingOSGraphState(thread_id="t1"))

    assert result["research_directive"].is_fallback_directive is True


def test_ceo_agent_node_strips_markdown_fences():
    directive_json = (
        '```json\n{"market_regime": "Bearish", "priority_sectors": [], '
        '"strategy_themes": [], "risk_tolerance": "Low", '
        '"participating_agents": [], "expected_outcomes": "x"}\n```'
    )
    with patch("src.agents.nodes.ceo.complete", return_value=_fake_response(directive_json)):
        result = ceo_agent_node(TradingOSGraphState(thread_id="t1"))

    assert result["research_directive"].market_regime == "Bearish"
    assert result["research_directive"].is_fallback_directive is False
