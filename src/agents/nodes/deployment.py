"""Deployment Agent node (AGT-012, PMPT-036/037) — REL-005 Epic E5.5. Terminal node of the graph.

Owns only the `Backtesting -> PaperTrading` recommendation. Never itself recommends or writes
`Strategy.status = "Live"` -- Business Rule 3 (human-in-the-loop) remains permanently behind the
RBAC-gated `/strategies/{id}/promote` endpoint (src/api/routers/strategies.py), which this node
never calls. `Strategy.status` writes for the statuses this node DOES own happen in
src/api/routers/agents.py's `_persist_strategy_progress`, not here -- like every other node in
this package, this is a pure function of `TradingOSGraphState` with no DB session.
"""

import json
from typing import Literal

import structlog

from src.agents.llm_router import complete
from src.agents.nodes.common import extract_json
from src.agents.prompt_registry import get_active_prompt
from src.agents.state import DeploymentRecommendation, TradingOSGraphState

PROMPT_SLUG = "deployment_agent"
TASK_PROMPT_SLUG = "deployment_agent_task"
logger = structlog.get_logger(__name__)


def _generate_rationale(
    hypothesis: str, optimization_summary: str, risk_summary: str, recommended_status: str
) -> str:
    try:
        system_prompt = get_active_prompt(PROMPT_SLUG)
        user_prompt = get_active_prompt(TASK_PROMPT_SLUG).format(
            hypothesis=hypothesis,
            optimization_summary=optimization_summary,
            risk_summary=risk_summary,
            recommended_status=recommended_status,
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
        return str(parsed["rationale"])
    except Exception as exc:  # noqa: BLE001 - rationale is advisory; never block the loop on it
        logger.warning("deployment_rationale_fallback", error=str(exc))
        return f"Recommending {recommended_status}: {risk_summary}"


def deployment_node(state: TradingOSGraphState) -> dict[str, object]:
    if state.risk_assessment is None:
        raise ValueError("deployment_node requires state.risk_assessment")

    hypothesis = state.strategy_logic.hypothesis if state.strategy_logic else "unknown strategy"
    optimization_summary = (
        state.optimization_result.notes if state.optimization_result else "unavailable"
    ) or "unavailable"
    risk_summary = state.risk_assessment.narrative

    recommended_status: Literal["Reject", "PaperTrading"] = (
        "Reject" if state.risk_assessment.decision == "Reject" else "PaperTrading"
    )

    rationale = _generate_rationale(
        hypothesis, optimization_summary, risk_summary, recommended_status
    )
    return {
        "deployment_recommendation": DeploymentRecommendation(
            recommended_status=recommended_status, rationale=rationale
        )
    }
