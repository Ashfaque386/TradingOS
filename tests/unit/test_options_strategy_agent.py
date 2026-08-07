"""REL-010 E10.4: Options Strategy Agent logic, mocked LLM -- the real hardcoded
scan_for_naked_options() gate is exercised for real (not mocked), matching this project's
established "hardcoded engine has final veto power" convention.

REL-030: options_strategy_node's own tests below mock generate_options_strategy() and
build_broker() directly -- generate_options_strategy()'s own real LLM/naked-options-scan
behavior is already covered by the tests above it, so the node tests focus on the new real
wiring logic (asset_class routing, chain-fetch failure/degradation, leg conversion) instead of
re-testing what's already proven."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.nodes.options_strategy_agent import (
    OptionsStrategyProposal,
    generate_options_strategy,
    options_strategy_node,
)
from src.agents.state import StrategyLogic, TradingOSGraphState
from src.brokers.base import OptionChain, OptionInstrument
from src.brokers.factory import NoBrokerConfigured
from src.engine.risk.naked_options_scanner import OptionLeg


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


def _equity_strategy() -> StrategyLogic:
    return StrategyLogic(
        hypothesis="SMA crossover",
        asset_class="Equity",
        style="Intraday",
        universe=["TCS"],
        entry_conditions="fast > slow",
        exit_conditions="fast < slow",
        stop_loss="2%",
        take_profit="4%",
        position_sizing="1% risk",
        confidence_score=0.8,
    )


def _fo_strategy(universe: list[str] | None = None) -> StrategyLogic:
    return StrategyLogic(
        hypothesis="Bear call spread on NIFTY, neutral-to-bearish view",
        asset_class="F&O",
        style="Intraday",
        universe=["NIFTY"] if universe is None else universe,
        entry_conditions="IV rank above 50",
        exit_conditions="50% of max profit captured",
        stop_loss="2x credit received",
        take_profit="50% of max credit",
        position_sizing="1 lot",
        confidence_score=0.7,
    )


def test_node_is_a_noop_for_an_equity_strategy():
    state = TradingOSGraphState(thread_id="t1", strategy_logic=_equity_strategy())
    assert options_strategy_node(state) == {}


def test_node_raises_when_strategy_logic_is_missing():
    state = TradingOSGraphState(thread_id="t1")
    with pytest.raises(ValueError, match="strategy_logic"):
        options_strategy_node(state)


def test_node_degrades_honestly_when_universe_is_empty():
    state = TradingOSGraphState(thread_id="t1", strategy_logic=_fo_strategy(universe=[]))
    result = options_strategy_node(state)
    assert result["strategy_logic"].option_legs is None


@patch("src.agents.nodes.options_strategy_agent.build_broker")
def test_node_degrades_honestly_when_no_broker_configured(mock_build_broker):
    mock_build_broker.side_effect = NoBrokerConfigured("no broker configured")
    state = TradingOSGraphState(thread_id="t1", strategy_logic=_fo_strategy())
    result = options_strategy_node(state)
    assert result["strategy_logic"].option_legs is None


@patch("src.agents.nodes.options_strategy_agent.build_broker")
def test_node_degrades_honestly_when_no_real_future_expiry_is_listed(mock_build_broker):
    mock_broker = mock_build_broker.return_value
    mock_broker.list_expiries = AsyncMock(return_value=[])
    state = TradingOSGraphState(thread_id="t1", strategy_logic=_fo_strategy())
    result = options_strategy_node(state)
    assert result["strategy_logic"].option_legs is None
    mock_broker.list_expiries.assert_awaited_once_with("NIFTY")


@patch("src.agents.nodes.options_strategy_agent.generate_options_strategy")
@patch("src.agents.nodes.options_strategy_agent.build_broker")
def test_node_degrades_honestly_when_no_grounded_proposal(mock_build_broker, mock_generate):
    mock_broker = mock_build_broker.return_value
    mock_broker.list_expiries = AsyncMock(return_value=[date(2026, 8, 6)])
    mock_broker.get_option_chain = AsyncMock(return_value=_real_chain())
    mock_generate.return_value = None

    state = TradingOSGraphState(thread_id="t1", strategy_logic=_fo_strategy())
    result = options_strategy_node(state)
    assert result["strategy_logic"].option_legs is None


@patch("src.agents.nodes.options_strategy_agent.generate_options_strategy")
@patch("src.agents.nodes.options_strategy_agent.build_broker")
def test_node_replaces_option_legs_with_a_real_chain_grounded_proposal(
    mock_build_broker, mock_generate
):
    mock_broker = mock_build_broker.return_value
    # list_expiries' own real contract (both real adapters honor it) is "sorted ascending" --
    # the node trusts that and takes the first element as nearest, rather than re-sorting.
    mock_broker.list_expiries = AsyncMock(return_value=[date(2026, 8, 6), date(2026, 8, 20)])
    mock_broker.get_option_chain = AsyncMock(return_value=_real_chain())
    mock_generate.return_value = OptionsStrategyProposal(
        legs=[
            OptionLeg(
                symbol="NIFTY26AUG24000CE",
                option_type="CE",
                strike=24000.0,
                side="sell",
                quantity=50,
            ),
            OptionLeg(
                symbol="NIFTY26AUG24200CE",
                option_type="CE",
                strike=24200.0,
                side="buy",
                quantity=50,
            ),
        ],
        rationale="Bear call spread, real chain-grounded.",
    )

    state = TradingOSGraphState(thread_id="t1", strategy_logic=_fo_strategy())
    result = options_strategy_node(state)

    # the nearest (earliest-sorted) real expiry is used, not just any listed one
    mock_broker.get_option_chain.assert_awaited_once_with("NIFTY", date(2026, 8, 6))
    legs = result["strategy_logic"].option_legs
    assert legs is not None
    assert len(legs) == 2
    assert legs[0].symbol == "NIFTY26AUG24000CE"
    assert legs[0].strike == 24000.0
    assert legs[0].side == "sell"
