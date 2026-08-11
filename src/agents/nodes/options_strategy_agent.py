"""Options Strategy Agent (AGT-015, PMPT-042/043, REL-010 E10.4, wired into production REL-030).

Proposes a defined-risk options structure (spread/condor) from a real, live options chain
(src/brokers/base.py::OptionChain, sourced via BrokerAdapter.get_option_chain). Every proposal is
run through the existing hardcoded `scan_for_naked_options()` (Phase 3 Epic E3.4,
src/engine/risk/naked_options_scanner.py) before being returned -- if the LLM's proposal is
somehow naked, it is rejected and retried (bounded), never surfaced. Advisory only: this agent
never places an order, matching Business Rule 3 (human/hardcoded-engine final authority).

REL-030: `generate_options_strategy()` above had zero production callers -- `StrategyLogic.
option_legs` (REL-016) was populated directly by the Strategy Generator Agent's own single LLM
call, free-handing option legs with no grounding against a real, live options chain and no
constraint against a fabricated strike. `options_strategy_node()` below is the real fix: a new
graph node, inserted between `strategy_generator` and `python_code_generator`, that -- only for
"F&O" strategies -- fetches a real nearest listed expiry (BrokerAdapter.list_expiries(), also new
this release) and a real option chain, then replaces the LLM's free-handed legs with this
module's real chain-grounded proposal. On any real failure to ground (no broker configured, no
real future expiry listed, the LLM producing nothing valid within its own retry budget), this
degrades honestly to `option_legs=None` -- the same "no structured leg data available" state
compliance_checker.py already treats as an honest skip, not a fabricated pass -- rather than
silently keeping the LLM's own ungrounded, unverified guess.

REL-035: a real, live bug found while scoping option-leg persistence for the Paper Trading
Account's daily signal job -- `options_strategy_agent_task`'s active prompt (registry.yaml)
never asks the LLM for a `symbol` field, so every real leg this agent has ever produced had
`symbol=""`. Fixed by resolving each leg's real broker symbol from the chain's own
`OptionInstrument.symbol` (`_symbol_lookup`) instead of trusting/defaulting the LLM's response --
this data was already available and grounded, it just wasn't being used.
"""

import asyncio
import json
from dataclasses import dataclass

import structlog

from src.agents.llm_router import complete
from src.agents.nodes.common import extract_json
from src.agents.prompt_registry import get_active_prompt
from src.agents.state import StrategyOptionLeg, TradingOSGraphState
from src.brokers.base import OptionChain
from src.brokers.factory import NoBrokerConfigured, build_broker
from src.engine.risk.naked_options_scanner import OptionLeg, scan_for_naked_options

PROMPT_SLUG = "options_strategy_agent"
TASK_PROMPT_SLUG = "options_strategy_agent_task"
logger = structlog.get_logger(__name__)

_MAX_ATTEMPTS = 2


@dataclass(frozen=True)
class OptionsStrategyProposal:
    legs: list[OptionLeg]
    rationale: str


def _summarize_chain(chain: OptionChain) -> str:
    return "; ".join(
        f"{i.option_type} {i.strike} (ltp={i.last_price}, oi={i.open_interest}, "
        f"iv={i.implied_volatility})"
        for i in chain.instruments
    )


def _symbol_lookup(chain: OptionChain) -> dict[tuple[float, str], str]:
    """REL-035: the real, tradable broker symbol for every (strike, option_type) pair the real
    chain actually lists -- used to resolve `StrategyOptionLeg.symbol` (the real per-contract
    identifier `execute_paper_trade` needs) at the one place that value is actually persisted,
    `options_strategy_node` below. Deliberately NOT used for `naked_options_scanner.OptionLeg.
    symbol` (see `_parse_legs`'s own docstring for why those are different fields with different
    meanings, despite the two classes' otherwise-identical shape)."""
    return {(i.strike, i.option_type): i.symbol for i in chain.instruments}


def _parse_legs(parsed: dict[str, object], chain: OptionChain, underlying: str) -> list[OptionLeg]:
    """Returns `naked_options_scanner.OptionLeg`s for the hedge-pairing check only -- `symbol`
    here is set to `underlying` (e.g. `"NIFTY"`), matching that module's own documented and
    tested meaning of the field ("same-underlying" grouping, confirmed by
    tests/unit/test_naked_options_scanner.py's own `test_hedge_on_a_different_underlying_does_
    not_count`), NOT the real per-contract broker symbol -- those are two different pieces of
    information this module's own `OptionLeg`/`StrategyOptionLeg` twin types happen to share a
    field name for. The real per-contract symbol is resolved separately in
    `options_strategy_node`, only where it's actually needed for persistence/trading."""
    raw_legs = parsed.get("legs", [])
    if not isinstance(raw_legs, list):
        raise ValueError("LLM response 'legs' was not a list")

    real_pairs = {(i.strike, i.option_type) for i in chain.instruments}
    legs: list[OptionLeg] = []
    for raw in raw_legs:
        strike = float(raw["strike"])
        option_type = raw["option_type"]
        if (strike, option_type) not in real_pairs:
            # Real, stricter validation than the old strike-only check: this also rejects a
            # real strike paired with an option_type that doesn't actually exist there.
            raise ValueError(f"LLM proposed ({option_type} {strike}) not present in the real chain")
        legs.append(
            OptionLeg(
                symbol=underlying,
                option_type=option_type,
                strike=strike,
                side=raw["side"],
                quantity=int(raw["quantity"]),
            )
        )
    return legs


def generate_options_strategy(
    *, underlying: str, chain: OptionChain, research_directive: str
) -> OptionsStrategyProposal | None:
    """Returns `None` (not a fabricated proposal) if no defined-risk structure could be produced
    within `_MAX_ATTEMPTS` real LLM attempts, or if the chain has no real instruments to build
    one from."""
    if not chain.instruments:
        logger.warning("options_strategy_no_chain_data", underlying=underlying)
        return None

    system_prompt = get_active_prompt(PROMPT_SLUG)
    user_prompt = get_active_prompt(TASK_PROMPT_SLUG).format(
        underlying=underlying,
        spot_price=chain.spot_price,
        expiry=chain.expiry.isoformat(),
        research_directive=research_directive,
        option_chain_summary=_summarize_chain(chain),
    )

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = complete(
                "research",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            content = response.choices[0].message.content
            parsed = json.loads(extract_json(content))
            legs = _parse_legs(parsed, chain, underlying)

            scan_result = scan_for_naked_options(legs)
            if scan_result.passed:
                return OptionsStrategyProposal(
                    legs=legs, rationale=str(parsed.get("rationale", ""))
                )

            logger.warning(
                "options_strategy_rejected_naked_proposal",
                underlying=underlying,
                attempt=attempt,
                naked_legs=[
                    leg.symbol or f"{leg.option_type}{leg.strike}" for leg in scan_result.naked_legs
                ],
            )
        except Exception as exc:  # noqa: BLE001 - a bad attempt is retried, not fatal
            logger.warning(
                "options_strategy_attempt_failed",
                underlying=underlying,
                attempt=attempt,
                error=str(exc),
            )

    logger.warning(
        "options_strategy_no_valid_proposal", underlying=underlying, attempts=_MAX_ATTEMPTS
    )
    return None


async def _fetch_nearest_chain(underlying: str) -> OptionChain | None:
    """`None` if no real future expiry is currently listed for `underlying` -- an honest "there
    is nothing to fetch" result, not an error."""
    broker = build_broker()
    expiries = await broker.list_expiries(underlying)
    if not expiries:
        return None
    return await broker.get_option_chain(underlying, expiries[0])


def options_strategy_node(state: TradingOSGraphState) -> dict[str, object]:
    if state.strategy_logic is None:
        raise ValueError("options_strategy_node requires a populated state.strategy_logic")

    if state.strategy_logic.asset_class != "F&O":
        return {}  # equity strategies: nothing for this node to ground

    underlying = state.strategy_logic.universe[0] if state.strategy_logic.universe else None
    if not underlying:
        logger.warning("options_strategy_node_no_underlying")
        return {"strategy_logic": state.strategy_logic.model_copy(update={"option_legs": None})}

    try:
        chain = asyncio.run(_fetch_nearest_chain(underlying))
    except NoBrokerConfigured:
        logger.warning("options_strategy_node_no_broker_configured", underlying=underlying)
        return {"strategy_logic": state.strategy_logic.model_copy(update={"option_legs": None})}
    except Exception as exc:  # noqa: BLE001 - a real broker/network failure degrades, not fatal
        logger.warning(
            "options_strategy_node_chain_fetch_failed", underlying=underlying, error=str(exc)
        )
        return {"strategy_logic": state.strategy_logic.model_copy(update={"option_legs": None})}

    if chain is None:
        logger.warning("options_strategy_node_no_real_future_expiry", underlying=underlying)
        return {"strategy_logic": state.strategy_logic.model_copy(update={"option_legs": None})}

    proposal = generate_options_strategy(
        underlying=underlying, chain=chain, research_directive=state.strategy_logic.hypothesis
    )
    if proposal is None:
        return {"strategy_logic": state.strategy_logic.model_copy(update={"option_legs": None})}

    # REL-035: `leg.symbol` here is `underlying` (see _parse_legs's own docstring) -- resolve
    # the real, tradable per-contract broker symbol from the chain for StrategyOptionLeg, which
    # persistence (src/api/routers/agents.py) and paper execution (src/engine/paper_trading/)
    # actually need. `.get(..., leg.symbol)` is a defensive fallback only, never expected to
    # fire: _parse_legs already validated every (strike, option_type) pair against this same
    # chain before returning `proposal.legs` in the first place.
    symbol_lookup = _symbol_lookup(chain)
    grounded_legs = [
        StrategyOptionLeg(
            symbol=symbol_lookup.get((leg.strike, leg.option_type), leg.symbol),
            option_type=leg.option_type,
            strike=leg.strike,
            side=leg.side,
            quantity=leg.quantity,
        )
        for leg in proposal.legs
    ]
    updated_strategy = state.strategy_logic.model_copy(update={"option_legs": grounded_legs})
    # REL-035: the expiry this proposal was actually grounded against, previously computed here
    # (via chain.expiry) and then discarded -- src/api/routers/agents.py::_persist_strategy_
    # progress now persists it alongside the legs onto StrategyVersion, since a leg itself has
    # no expiry field (one expiry applies to the whole proposal, not per-leg).
    return {"strategy_logic": updated_strategy, "option_expiry": chain.expiry}
