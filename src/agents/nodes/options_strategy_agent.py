"""Options Strategy Agent (AGT-015, PMPT-042/043, REL-010 E10.4).

Proposes a defined-risk options structure (spread/condor) from a real, live options chain
(src/brokers/base.py::OptionChain, sourced via BrokerAdapter.get_option_chain). Every proposal is
run through the existing hardcoded `scan_for_naked_options()` (Phase 3 Epic E3.4,
src/engine/risk/naked_options_scanner.py) before being returned -- if the LLM's proposal is
somehow naked, it is rejected and retried (bounded), never surfaced. Advisory only: this agent
never places an order, matching Business Rule 3 (human/hardcoded-engine final authority).
"""

import json
from dataclasses import dataclass

import structlog

from src.agents.llm_router import complete
from src.agents.nodes.common import extract_json
from src.agents.prompt_registry import get_active_prompt
from src.brokers.base import OptionChain
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


def _real_strikes(chain: OptionChain) -> set[float]:
    return {i.strike for i in chain.instruments}


def _parse_legs(parsed: dict[str, object], real_strikes: set[float]) -> list[OptionLeg]:
    raw_legs = parsed.get("legs", [])
    if not isinstance(raw_legs, list):
        raise ValueError("LLM response 'legs' was not a list")

    legs: list[OptionLeg] = []
    for raw in raw_legs:
        strike = float(raw["strike"])
        if strike not in real_strikes:
            raise ValueError(f"LLM proposed a strike ({strike}) not present in the real chain")
        legs.append(
            OptionLeg(
                symbol=str(raw.get("symbol", "")),
                option_type=raw["option_type"],
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

    real_strikes = _real_strikes(chain)
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
            legs = _parse_legs(parsed, real_strikes)

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
