"""Compliance Agent node (AGT-020, PMPT-038/039) -- REL-006 Epic E6.1.

Advisory only -- the hardcoded, deterministic compliance checker
(src/engine/risk/compliance_checker.py) retains final Pass/Block authority, matching this
codebase's established "hardcoded engine has final veto power" convention (same as
risk_manager.py). This node runs that checker against whatever data is available in
TradingOSGraphState at the pre-deployment strategy-review stage, then asks an LLM to narrate the
real result.

Honest gap (unchanged from risk_manager.py's own documented gap, re-confirmed for REL-006, not
re-guessed): no real order quantity exists yet at this stage (Position Sizing isn't threaded
into TradingOSGraphState), and no structured OptionLeg data exists either (StrategyLogic is
plain-text conditions, not structured legs). `evaluate_compliance()` is called with only the
strategy's first universe symbol and no quantity/legs, so `position_limit_checked`,
`circuit_filter_checked`, and `naked_options_checked` are honestly False here -- this node
therefore Passes essentially every strategy at the graph-review stage. The real teeth of AGT-020
is the live execution-pipeline pre-trade check (src/engine/live/execution_pipeline.py's
`compliance_pre_trade_check`), where a real TradeSignal carries real quantity/price/option_legs
-- see that module for the check that actually has data to block on.
"""

import json

import structlog

from src.agents.llm_router import complete
from src.agents.nodes.common import extract_json
from src.agents.prompt_registry import get_active_prompt
from src.agents.state import ComplianceVerdict, TradingOSGraphState
from src.engine.risk.compliance_checker import evaluate_compliance

PROMPT_SLUG = "compliance_agent"
TASK_PROMPT_SLUG = "compliance_agent_task"
logger = structlog.get_logger(__name__)


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
        return (
            f"Compliance verdict: {verdict}. {violations_summary} "
            "Position-limit and circuit-filter checks were not run (no concrete order quantity "
            "exists at this pre-deployment stage). Naked-options check was not run (no "
            "structured option-leg data available from this strategy's plain-text logic)."
        )


def compliance_node(state: TradingOSGraphState) -> dict[str, object]:
    if state.python_code is None:
        raise ValueError("compliance_node requires state.python_code")

    symbol = (
        state.strategy_logic.universe[0]
        if state.strategy_logic and state.strategy_logic.universe
        else "UNKNOWN"
    )
    result = evaluate_compliance(symbol=symbol)

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
