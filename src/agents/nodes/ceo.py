"""CEO Agent node (AGT-001, PMPT-001) — Phase 2 Epic E2.3.

Daily trigger producing the Executive Research Directive. Per Phase_4_AI_Agent_Design.md §1
Error Handling: "If global data APIs fail, default to a neutral, delta-hedged research
directive" -- here that's generalized to any failure (LLM call, JSON parse) so the pipeline
never halts on this node.
"""

import structlog

from src.agents.llm_router import complete
from src.agents.nodes.common import extract_json
from src.agents.prompt_registry import get_active_prompt
from src.agents.state import ResearchDirective, TradingOSGraphState

PROMPT_SLUG = "ceo_agent"
TASK_PROMPT_SLUG = "ceo_agent_task"
logger = structlog.get_logger(__name__)

_FALLBACK_DIRECTIVE = ResearchDirective(
    market_regime="Sideways",
    priority_sectors=[],
    strategy_themes=[],
    risk_tolerance="Low",
    participating_agents=["MarketAnalystAgent", "StrategyGeneratorAgent"],
    expected_outcomes="Fallback neutral directive issued due to an upstream failure.",
    is_fallback_directive=True,
)


def ceo_agent_node(state: TradingOSGraphState) -> dict[str, ResearchDirective]:
    system_prompt = get_active_prompt(PROMPT_SLUG)
    user_prompt = get_active_prompt(TASK_PROMPT_SLUG).format(
        schema=ResearchDirective.model_json_schema()
    )
    try:
        response = complete(
            "orchestration",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        directive = ResearchDirective.model_validate_json(extract_json(content))
    except Exception as exc:  # noqa: BLE001 - any failure here must degrade gracefully, not halt
        logger.warning("ceo_agent_fallback", error=str(exc))
        directive = _FALLBACK_DIRECTIVE

    return {"research_directive": directive}
