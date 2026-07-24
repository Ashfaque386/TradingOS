from unittest.mock import MagicMock, patch

import pytest

from src.agents.nodes.market_analyst import market_analyst_node
from src.agents.state import TradingOSGraphState


def _fake_response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices[0].message.content = content
    return response


_VALID_CONTEXT_JSON = (
    '{"market_regime": "Sideways", "sector_rankings": ["IT", "Pharma"], '
    '"volatility_assessment": "Low", "macro_outlook": "Stable", '
    '"confidence_score": 0.6, "insights": ["Range-bound"]}'
)


def test_market_analyst_node_parses_valid_context_and_notes_missing_skills():
    with (
        patch(
            "src.agents.nodes.market_analyst.complete",
            return_value=_fake_response(_VALID_CONTEXT_JSON),
        ),
        patch("src.agents.nodes.market_analyst._try_skill", return_value=None),
    ):
        result = market_analyst_node(TradingOSGraphState(thread_id="t1"))

    assert result["market_context"].market_regime == "Sideways"


def test_market_analyst_node_retries_up_to_three_times_then_raises():
    with (
        patch(
            "src.agents.nodes.market_analyst.complete", side_effect=RuntimeError("timeout")
        ) as mock_complete,
        patch("src.agents.nodes.market_analyst._try_skill", return_value=None),
        pytest.raises(RuntimeError, match="failed after 3 retries"),
    ):
        market_analyst_node(TradingOSGraphState(thread_id="t1"))

    assert mock_complete.call_count == 3


def test_market_analyst_node_succeeds_after_transient_failure():
    responses = [RuntimeError("timeout"), _fake_response(_VALID_CONTEXT_JSON)]
    with (
        patch("src.agents.nodes.market_analyst.complete", side_effect=responses),
        patch("src.agents.nodes.market_analyst._try_skill", return_value=None),
    ):
        result = market_analyst_node(TradingOSGraphState(thread_id="t1"))

    assert result["market_context"].market_regime == "Sideways"
