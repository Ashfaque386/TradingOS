"""Evaluator Agent node (AGT-011, PMPT-032/033) — REL-005 Epic E5.2.

Gatekeeper of the Backtest_Loop. The PASS/FAIL verdict itself is computed deterministically,
never by the LLM -- Sharpe Ratio > 1.5 is the only numeric threshold specified anywhere in this
project's design corpus (SRS Workflow 1 step 7, echoed in Phase_3/Phase_13). Max drawdown, win
rate, and profit factor are surfaced as supporting context in the LLM-generated feedback, not
additional hard gates: no numeric cutoff for them exists anywhere in the design docs, and this
project's convention (established for the hardcoded risk engine, src/engine/risk/) is to never
invent a business threshold that wasn't actually specified. This is an interim, explicitly
documented decision -- a real threshold table sourced from the active ResearchDirective is future
scope, not fabricated here.

The 5-consecutive-rejection escalation to the CEO Agent (Phase_4_AI_Agent_Design.md §11) is
enforced by graph.py's conditional routing reading `state.strategy_rejection_count` (incremented
by strategy_generator_node, not here) -- this node only produces the verdict that routing decides
on. The counter itself is reset by `ceo_agent_node` on every entry, so a fresh escalated cycle
gets a fresh 5-strikes budget.
"""

import json

import structlog

from src.agents.llm_router import complete
from src.agents.nodes.common import extract_json
from src.agents.prompt_registry import get_active_prompt
from src.agents.state import EvaluationVerdict, TradingOSGraphState

PROMPT_SLUG = "evaluator_agent"
TASK_PROMPT_SLUG = "evaluator_agent_task"
SHARPE_PASS_THRESHOLD = 1.5
logger = structlog.get_logger(__name__)


def _generate_feedback(hypothesis: str, metrics_json: str, failure_reasons: list[str]) -> str:
    try:
        system_prompt = get_active_prompt(PROMPT_SLUG)
        user_prompt = get_active_prompt(TASK_PROMPT_SLUG).format(
            hypothesis=hypothesis, metrics_json=metrics_json, failure_reasons=failure_reasons
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
        return str(parsed["feedback"])
    except Exception as exc:  # noqa: BLE001 - feedback is advisory; never block the loop on it
        logger.warning("evaluator_feedback_fallback", error=str(exc))
        return f"Backtest failed: {'; '.join(failure_reasons)}"


def evaluator_node(state: TradingOSGraphState) -> dict[str, object]:
    if state.backtest_metrics is None:
        raise ValueError("evaluator_node requires state.backtest_metrics")
    metrics = state.backtest_metrics

    failure_reasons: list[str] = []
    if metrics.sharpe_ratio <= SHARPE_PASS_THRESHOLD:
        failure_reasons.append(
            f"Sharpe Ratio {metrics.sharpe_ratio:.2f} does not exceed the "
            f"{SHARPE_PASS_THRESHOLD} pass threshold"
        )

    if not failure_reasons:
        return {
            "evaluation_verdict": EvaluationVerdict(
                verdict="PASS", failure_reasons=[], feedback_for_strategy_generator=None
            )
        }

    hypothesis = state.strategy_logic.hypothesis if state.strategy_logic else "unknown strategy"
    feedback = _generate_feedback(hypothesis, metrics.model_dump_json(), failure_reasons)
    return {
        "evaluation_verdict": EvaluationVerdict(
            verdict="FAIL",
            failure_reasons=failure_reasons,
            feedback_for_strategy_generator=feedback,
        )
    }
