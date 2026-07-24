"""Strategy Generator Agent node (AGT-003, PMPT-003) — Phase 2 Epic E2.3.

Queries the real Qdrant `trading_strategies` RAG collection (query_qdrant_strategy_memory,
src/agents/tools/skills.py) before ideating, per Phase_4_AI_Agent_Design.md §3. Tracks
strategy_rejection_count: if the prior loop iteration's EvaluationVerdict was FAIL, this
increments the counter; per the escalation rule, 5 consecutive rejections should route to the
CEO Agent instead of looping back here again (enforced by graph.py's conditional edge, not
this node -- this node only tracks the count).
"""

import structlog

from src.agents.llm_router import complete
from src.agents.nodes.common import extract_json
from src.agents.prompt_registry import get_active_prompt
from src.agents.state import StrategyLogic, TradingOSGraphState
from src.agents.tools.registry import get_skill_registry

PROMPT_SLUG = "strategy_generator_agent"
TASK_PROMPT_SLUG = "strategy_generator_agent_task"
MAX_REJECTIONS_BEFORE_ESCALATION = 5
logger = structlog.get_logger(__name__)


def strategy_generator_node(state: TradingOSGraphState) -> dict[str, object]:
    system_prompt = get_active_prompt(PROMPT_SLUG)

    rejection_count = state.strategy_rejection_count
    if state.evaluation_verdict is not None and state.evaluation_verdict.verdict == "FAIL":
        rejection_count += 1
        logger.info(
            "strategy_rejection_incremented",
            rejection_count=rejection_count,
            reasons=state.evaluation_verdict.failure_reasons,
        )

    query_text = (
        state.research_directive.expected_outcomes
        if state.research_directive
        else "general Indian equity strategy"
    )
    past_strategies = get_skill_registry().execute(
        "query_qdrant_strategy_memory", query=query_text, top_k=5
    )

    directive_json = (
        state.research_directive.model_dump_json() if state.research_directive else "none"
    )
    context_json = state.market_context.model_dump_json() if state.market_context else "none"

    rejection_feedback = ""
    if state.evaluation_verdict is not None and state.evaluation_verdict.verdict == "FAIL":
        rejection_feedback = (
            f"Your previous attempt was rejected ({rejection_count} consecutive rejection(s)): "
            f"{state.evaluation_verdict.feedback_for_strategy_generator}\n"
        )

    user_prompt = get_active_prompt(TASK_PROMPT_SLUG).format(
        directive_json=directive_json,
        context_json=context_json,
        past_strategies=past_strategies,
        rejection_feedback=rejection_feedback,
        schema=StrategyLogic.model_json_schema(),
    )

    response = complete(
        "coding",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    content = response.choices[0].message.content
    strategy = StrategyLogic.model_validate_json(extract_json(content))

    return {"strategy_logic": strategy, "strategy_rejection_count": rejection_count}
