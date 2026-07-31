"""REL-010 E10.4: Options Strategy Agent logic, mocked LLM -- the real hardcoded
scan_for_naked_options() gate is exercised for real (not mocked), matching this project's
established "hardcoded engine has final veto power" convention."""

from datetime import date
from unittest.mock import patch

from src.agents.nodes.options_strategy_agent import generate_options_strategy
from src.brokers.base import OptionChain, OptionInstrument


def _fake_response(content: str):
    class _Choice:
        def __init__(self, content: str) -> None:
            self.message = type("Message", (), {"content": content})()

    class _Response:
        def __init__(self, content: str) -> None:
            self.choices = [_Choice(content)]

    return _Response(content)


def _real_chain() -> OptionChain:
    return OptionChain(
        underlying="NIFTY",
        expiry=date(2026, 8, 6),
        spot_price=24100.0,
        instruments=[
            OptionInstrument(
                symbol="NIFTY26AUG24000CE",
                underlying="NIFTY",
                strike=24000.0,
                option_type="CE",
                expiry=date(2026, 8, 6),
                last_price=150.0,
                open_interest=1000,
                implied_volatility=0.15,
            ),
            OptionInstrument(
                symbol="NIFTY26AUG24200CE",
                underlying="NIFTY",
                strike=24200.0,
                option_type="CE",
                expiry=date(2026, 8, 6),
                last_price=80.0,
                open_interest=800,
                implied_volatility=0.16,
            ),
        ],
    )


@patch("src.agents.nodes.options_strategy_agent.complete")
def test_accepts_a_valid_defined_risk_spread(mock_complete):
    mock_complete.return_value = _fake_response(
        '{"legs": ['
        '{"strike": 24000, "option_type": "CE", "side": "sell", "quantity": 50}, '
        '{"strike": 24200, "option_type": "CE", "side": "buy", "quantity": 50}'
        '], "rationale": "Bear call spread on a neutral-to-bearish view."}'
    )

    proposal = generate_options_strategy(
        underlying="NIFTY", chain=_real_chain(), research_directive="Neutral to bearish on NIFTY"
    )

    assert proposal is not None
    assert len(proposal.legs) == 2
    assert proposal.rationale


@patch("src.agents.nodes.options_strategy_agent.complete")
def test_rejects_a_naked_short_and_retries_then_succeeds(mock_complete):
    naked_response = _fake_response(
        '{"legs": [{"strike": 24000, "option_type": "CE", "side": "sell", "quantity": 50}], '
        '"rationale": "naive"}'
    )
    hedged_response = _fake_response(
        '{"legs": ['
        '{"strike": 24000, "option_type": "CE", "side": "sell", "quantity": 50}, '
        '{"strike": 24200, "option_type": "CE", "side": "buy", "quantity": 50}'
        '], "rationale": "corrected, hedged"}'
    )
    mock_complete.side_effect = [naked_response, hedged_response]

    proposal = generate_options_strategy(
        underlying="NIFTY", chain=_real_chain(), research_directive="test"
    )

    assert proposal is not None
    assert mock_complete.call_count == 2
    assert proposal.rationale == "corrected, hedged"


@patch("src.agents.nodes.options_strategy_agent.complete")
def test_returns_none_if_every_attempt_is_naked(mock_complete):
    always_naked = _fake_response(
        '{"legs": [{"strike": 24000, "option_type": "CE", "side": "sell", "quantity": 50}], '
        '"rationale": "naive"}'
    )
    mock_complete.return_value = always_naked

    proposal = generate_options_strategy(
        underlying="NIFTY", chain=_real_chain(), research_directive="test"
    )

    assert proposal is None


@patch("src.agents.nodes.options_strategy_agent.complete")
def test_rejects_a_strike_not_present_in_the_real_chain(mock_complete):
    fabricated_strike = _fake_response(
        '{"legs": ['
        '{"strike": 99999, "option_type": "CE", "side": "sell", "quantity": 50}, '
        '{"strike": 100000, "option_type": "CE", "side": "buy", "quantity": 50}'
        '], "rationale": "bad"}'
    )
    mock_complete.return_value = fabricated_strike

    proposal = generate_options_strategy(
        underlying="NIFTY", chain=_real_chain(), research_directive="test"
    )

    assert proposal is None  # both attempts fail to parse -- a fabricated strike is never used


def test_returns_none_for_an_empty_chain():
    empty_chain = OptionChain(
        underlying="NIFTY", expiry=date(2026, 8, 6), spot_price=24100.0, instruments=[]
    )
    proposal = generate_options_strategy(
        underlying="NIFTY", chain=empty_chain, research_directive="test"
    )
    assert proposal is None
