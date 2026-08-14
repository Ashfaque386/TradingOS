"""Compliance Agent node (AGT-020, PMPT-038/039) -- REL-006 Epic E6.1.

Advisory only -- the hardcoded, deterministic compliance checker
(src/engine/risk/compliance_checker.py) retains final Pass/Block authority, matching this
codebase's established "hardcoded engine has final veto power" convention (same as
risk_manager.py). This node runs that checker against whatever data is available in
TradingOSGraphState at the pre-deployment strategy-review stage, then asks an LLM to narrate the
real result.

REL-016 E16.3 (GLH-09) closed the naked-options half of this node's original gap: for "F&O"
strategies, `state.strategy_logic.option_legs` (Strategy Generator Agent prompt v2, PMPT-029) now
gives `evaluate_compliance()` real declared legs, so a genuinely naked leg produces a real
`verdict="Block"` here -- this node's actual veto power, not just advisory narration.

UPDATE 2026-08-14: the position-limit half of this node's other original gap is now closed too.
`compliance_node` runs before `backtesting`/`risk_manager` in the graph (see graph.py's
`build_graph()`), so `state.risk_assessment.position_sizing_shares` genuinely does not exist yet
at this point and can't be reused -- rather than reorder the graph or leave this permanently
unchecked, `_estimate_conservative_quantity` below sources a real, non-fabricated CONSERVATIVE
upper-bound quantity from `state.account_capital` and the candidate symbol's latest real close
price (same DataLake source risk_manager.py already uses for `^NSEI`): "if the full account's
capital were allocated to this one symbol, how many shares?" This is deliberately a different,
more conservative figure than Risk Manager's own later inverse-volatility-weighted sizing, not a
duplicate of it -- it exists only to give the hardcoded position-limit check a real number to
compare against at this earlier pipeline stage. `position_limit_checked` is now real whenever
`state.account_capital` and real price data both exist; still honestly False when either is
missing (a young Paper account, or a symbol with no ingested OHLCV history).

`circuit_filter_checked` stays honestly False here, permanently, not as an open gap: it needs a
real `limit_price`, a concept that genuinely does not exist until an actual order is being placed
-- the real teeth for that check is the live execution-pipeline pre-trade check
(src/engine/live/execution_pipeline.py's `compliance_pre_trade_check`), where a real TradeSignal
carries a real limit_price -- see that module for the check that actually has data to block on.
"""

import json

import structlog

from src.agents.llm_router import complete
from src.agents.nodes.common import extract_json
from src.agents.prompt_registry import get_active_prompt
from src.agents.state import ComplianceVerdict, TradingOSGraphState
from src.core.config import get_settings
from src.data.datalake.query import DataLake
from src.engine.risk.compliance_checker import evaluate_compliance
from src.engine.risk.naked_options_scanner import OptionLeg

PROMPT_SLUG = "compliance_agent"
TASK_PROMPT_SLUG = "compliance_agent_task"
logger = structlog.get_logger(__name__)


def _latest_close_price(symbol: str) -> float | None:
    data_lake = DataLake(get_settings().data_lake_root / "ohlcv_daily")
    df = data_lake.read_symbol(symbol, None, None)
    if df.is_empty():
        return None
    return float(df.sort("date")["close"][-1])


def _estimate_conservative_quantity(state: TradingOSGraphState, symbol: str) -> int | None:
    """A conservative "entire account capital into this one symbol" upper-bound quantity --
    None (not fabricated) whenever no real account_capital or no real price data exists."""
    if state.account_capital is None:
        return None
    price = _latest_close_price(symbol)
    if price is None or price <= 0:
        return None
    return int(state.account_capital // price)


def _generate_narrative(
    *, hypothesis: str, verdict: str, violations_summary: str, checker_result: object
) -> str:
    try:
        system_prompt = get_active_prompt(PROMPT_SLUG)
        user_prompt = get_active_prompt(TASK_PROMPT_SLUG).format(
            hypothesis=hypothesis,
            verdict=verdict,
            violations_summary=violations_summary,
            position_limit_checked=checker_result.position_limit_checked,  # type: ignore[attr-defined]
            circuit_filter_checked=checker_result.circuit_filter_checked,  # type: ignore[attr-defined]
            naked_options_checked=checker_result.naked_options_checked,  # type: ignore[attr-defined]
        )
        response = complete(
            "research",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        parsed = json.loads(extract_json(content))
        return str(parsed["narrative"])
    except Exception as exc:  # noqa: BLE001 - narrative is advisory; never block the loop on it
        logger.warning("compliance_narrative_fallback", error=str(exc))
        position_limit_note = (
            "Position-limit check ran against a conservative estimated quantity."
            if checker_result.position_limit_checked  # type: ignore[attr-defined]
            else "Position-limit check was not run (no account capital or price data available)."
        )
        naked_options_note = (
            "Naked-options check ran against real declared option legs."
            if checker_result.naked_options_checked  # type: ignore[attr-defined]
            else "Naked-options check was not run (no structured option-leg data available from "
            "this strategy's plain-text logic)."
        )
        return (
            f"Compliance verdict: {verdict}. {violations_summary} {position_limit_note} "
            "Circuit-filter check was not run (no limit price exists at this pre-deployment "
            f"stage). {naked_options_note}"
        )


def compliance_node(state: TradingOSGraphState) -> dict[str, object]:
    if state.python_code is None:
        raise ValueError("compliance_node requires state.python_code")

    symbol = (
        state.strategy_logic.universe[0]
        if state.strategy_logic and state.strategy_logic.universe
        else "UNKNOWN"
    )
    declared_legs = state.strategy_logic.option_legs if state.strategy_logic else None
    option_legs = (
        [
            OptionLeg(
                symbol=leg.symbol,
                option_type=leg.option_type,
                strike=leg.strike,
                side=leg.side,
                quantity=leg.quantity,
            )
            for leg in declared_legs
        ]
        if declared_legs
        else None
    )
    quantity = _estimate_conservative_quantity(state, symbol)
    result = evaluate_compliance(symbol=symbol, quantity=quantity, option_legs=option_legs)

    violations_summary = (
        "; ".join(f"{v.rule}: {v.detail}" for v in result.violations)
        if result.violations
        else "No violations."
    )
    hypothesis = state.strategy_logic.hypothesis if state.strategy_logic else "unknown strategy"
    narrative = _generate_narrative(
        hypothesis=hypothesis,
        verdict=result.verdict,
        violations_summary=violations_summary,
        checker_result=result,
    )

    return {
        "compliance_verdict": ComplianceVerdict(
            verdict=result.verdict,
            violations=[f"{v.rule}: {v.detail}" for v in result.violations],
            naked_options_checked=result.naked_options_checked,
            position_limit_checked=result.position_limit_checked,
            circuit_filter_checked=result.circuit_filter_checked,
            narrative=narrative,
        )
    }
