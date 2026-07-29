"""Risk Manager Agent node (AGT-008, PMPT-034/035) — REL-005 Epic E5.4.

Advisory only -- the hardcoded, deterministic risk engine (src/engine/risk/) retains final veto
power (Phase_4_AI_Agent_Design.md §8: "the hardcoded engine has final veto power"). The kill
switch check is the one real, hard gate this node enforces:
`kill_switch_service.is_tripped()`, backed by real DB state
(src/engine/risk/kill_switch_service.py).

Correlation and naked-options checks are honestly NOT run against real data this pass -- verified
during REL-005 implementation, not assumed:
  - `correlation.check_correlation_constraint()` needs a real Nifty 50 benchmark return series;
    the real data lake (checked directly, not guessed) has never ingested any index/benchmark
    symbol, only 5 individual large-cap stocks (RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK). There
    is also no historical portfolio-equity-curve table to derive "existing portfolio returns"
    from, only current position snapshots.
  - `naked_options_scanner.scan_for_naked_options()` needs structured `OptionLeg` data; nothing
    in this pipeline produces structured legs from LLM-generated Python strategy code or from
    `StrategyLogic` (plain-text conditions only).
  - Position sizing (`position_sizing.compute_position_sizes`) needs real account capital, which
    isn't threaded into `TradingOSGraphState` anywhere.
Rather than fabricate a result for any of these, the node returns `decision=
"ApproveWithRestrictions"` (never a clean "Approve") whenever the kill switch itself is armed,
and the narrative says plainly what wasn't checked and why -- matching this codebase's
established honestly-stubbed-capability convention (src/agents/tools/skills.py's
SkillNotImplementedError).
"""

import json

import structlog

from src.agents.llm_router import complete
from src.agents.nodes.common import extract_json
from src.agents.prompt_registry import get_active_prompt
from src.agents.state import RiskAssessment, TradingOSGraphState
from src.engine.risk import kill_switch_service

PROMPT_SLUG = "risk_manager_agent"
TASK_PROMPT_SLUG = "risk_manager_agent_task"
NOT_COMPUTED_NOTE = "Not checked this pass -- no real data source available (see module docstring)."
logger = structlog.get_logger(__name__)


def _generate_narrative(hypothesis: str) -> str:
    try:
        system_prompt = get_active_prompt(PROMPT_SLUG)
        user_prompt = get_active_prompt(TASK_PROMPT_SLUG).format(
            hypothesis=hypothesis,
            kill_switch_tripped=False,
            correlation_summary=NOT_COMPUTED_NOTE,
            naked_options_summary=NOT_COMPUTED_NOTE,
            position_sizing_summary=NOT_COMPUTED_NOTE,
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
        logger.warning("risk_manager_narrative_fallback", error=str(exc))
        return (
            "Kill switch armed (not tripped). Correlation, naked-options, and position-sizing "
            f"checks were not run: {NOT_COMPUTED_NOTE}"
        )


def risk_manager_node(state: TradingOSGraphState) -> dict[str, object]:
    if state.optimization_result is None or not state.optimization_result.passed:
        raise ValueError("risk_manager_node requires a passed state.optimization_result")

    if kill_switch_service.is_tripped():
        return {
            "risk_assessment": RiskAssessment(
                decision="Reject",
                kill_switch_tripped=True,
                correlation_passed=None,
                naked_options_checked=False,
                narrative=(
                    "Kill switch is TRIPPED -- the hardcoded Risk Engine has already halted all "
                    "AI deployment loops. No further risk-relevant recommendation is possible "
                    "until a human resets it (API-086)."
                ),
            )
        }

    hypothesis = state.strategy_logic.hypothesis if state.strategy_logic else "unknown strategy"
    narrative = _generate_narrative(hypothesis)
    return {
        "risk_assessment": RiskAssessment(
            decision="ApproveWithRestrictions",
            kill_switch_tripped=False,
            correlation_passed=None,
            naked_options_checked=False,
            narrative=narrative,
        )
    }
