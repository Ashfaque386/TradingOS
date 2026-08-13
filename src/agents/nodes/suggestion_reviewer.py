"""Suggestion Reviewer Agent (PMPT-046/047) — REL-048.

Not a LangGraph node -- unlike every other agent under `src/agents/nodes/`, this runs standalone
from `src/api/routers/strategies.py`'s suggestion-review background job, judging a human's
free-text suggestion against a strategy's *current, already-persisted* logic and latest backtest
verdict (read straight from the DB, not from `TradingOSGraphState`). If judged sound, the caller
re-enters the real agent pipeline via `build_suggestion_regeneration_graph()`
(`src/agents/graph.py`) with this suggestion folded into a synthetic FAIL `EvaluationVerdict` --
the same `rejection_feedback` code path `strategy_generator_node` already proves works for the
Evaluator's own FAIL-retry loop.
"""

import json

import structlog

from src.agents.llm_router import complete
from src.agents.nodes.common import extract_json
from src.agents.prompt_registry import get_active_prompt
from src.agents.state import StrictModel

PROMPT_SLUG = "suggestion_reviewer_agent"
TASK_PROMPT_SLUG = "suggestion_reviewer_agent_task"
logger = structlog.get_logger(__name__)


class SuggestionVerdict(StrictModel):
    sound: bool
    reasoning: str


def review_suggestion(
    strategy_logic_summary: dict[str, object],
    backtest_verdict_summary: dict[str, object] | None,
    suggestion_text: str,
) -> SuggestionVerdict:
    system_prompt = get_active_prompt(PROMPT_SLUG)
    user_prompt = get_active_prompt(TASK_PROMPT_SLUG).format(
        strategy_logic_json=json.dumps(strategy_logic_summary),
        backtest_verdict_json=(
            json.dumps(backtest_verdict_summary) if backtest_verdict_summary else "none"
        ),
        suggestion_text=suggestion_text,
    )
    response = complete(
        "research",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    content = response.choices[0].message.content
    return SuggestionVerdict.model_validate_json(extract_json(content))
