"""Model Evaluator Agent node (AGT-019, PMPT-019/042) -- REL-008 E8.6.

"Last line of defense" per its own design-doc prompt: computes a real Promote/Reject/Shadow-Test
recommendation by comparing the candidate's real metrics against the current real Production
model of the same type (a real Postgres query, not a fabricated comparison) -- but this node's
output is a recommendation only. It never calls POST /ml/models/{id}/promote itself; that always
requires a separate, human-role-gated (PortfolioManager/SystemAdministrator) API call, matching
AGT-017/018's own "never promote yourself" prompt lines.

Promotion margin confirmed with the user (AskUserQuestion, REL-008 planning): a candidate must
beat the current Production model by >=5% relative improvement to be recommended Promote (not
just Shadow-Test). RL candidates instead reuse SHARPE_PASS_THRESHOLD=1.5
(src/agents/nodes/evaluator.py) -- the one existing real numeric bar already established in this
codebase for backtest Sharpe -- since there is no meaningful "relative improvement" framing for a
policy's own Sharpe versus a rule-based strategy's.
"""

import json
from typing import Literal

import structlog
from sqlalchemy import select

from src.agents.llm_router import complete
from src.agents.nodes.common import extract_json
from src.agents.nodes.evaluator import SHARPE_PASS_THRESHOLD
from src.agents.prompt_registry import get_active_prompt
from src.agents.state import ModelEvaluationVerdict, TradingOSGraphState
from src.core.db import get_session
from src.models.ml import MLModel

PROMPT_SLUG = "model_evaluator_agent"
TASK_PROMPT_SLUG = "model_evaluator_agent_task"
PROMOTION_MARGIN = 0.05
logger = structlog.get_logger(__name__)

# Lower values are better for these metrics -- "improvement" flips sign accordingly.
_LOWER_IS_BETTER = {"test_mae"}


def _generate_report(
    *,
    candidate_id: str,
    production_id: str | None,
    decision: str,
    metric_deltas: dict[str, float],
    confidence_score: float,
) -> str:
    try:
        system_prompt = get_active_prompt(PROMPT_SLUG)
        user_prompt = get_active_prompt(TASK_PROMPT_SLUG).format(
            candidate_ml_model_id=candidate_id,
            production_ml_model_id=production_id or "none (first model of this type)",
            decision=decision,
            metric_deltas_summary=json.dumps(metric_deltas),
            confidence_score=round(confidence_score, 3),
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
        return str(parsed["comparison_report"])
    except Exception as exc:  # noqa: BLE001 - report is advisory; never block the loop on it
        logger.warning("model_evaluator_report_fallback", error=str(exc))
        return (
            f"Decision: {decision}. Metric deltas: {metric_deltas}. "
            f"Confidence: {confidence_score:.2f}."
        )


def _primary_metric(metrics: dict[str, float]) -> tuple[str, float] | None:
    for key in ("test_accuracy", "test_mae", "backtest_sharpe"):
        if key in metrics:
            return key, metrics[key]
    return None


def model_evaluator_node(state: TradingOSGraphState) -> dict[str, object]:
    model_type: str
    if state.ml_training_result is not None:
        candidate_id = state.ml_training_result.ml_model_id
        model_type = state.ml_training_result.model_type
        candidate_metrics = state.ml_training_result.metrics
    elif state.rl_training_result is not None:
        candidate_id = state.rl_training_result.ml_model_id
        model_type = f"{state.rl_training_result.algorithm}-RL"
        candidate_metrics = {"backtest_sharpe": state.rl_training_result.backtest_sharpe or 0.0}
    else:
        raise ValueError(
            "model_evaluator_node requires state.ml_training_result or state.rl_training_result"
        )

    primary = _primary_metric(candidate_metrics)
    if primary is None:
        raise ValueError(
            f"candidate metrics have no recognized primary metric: {candidate_metrics}"
        )
    metric_name, candidate_value = primary

    with get_session() as session:
        production = session.scalars(
            select(MLModel)
            .where(MLModel.model_type == model_type, MLModel.stage == "Production")
            .order_by(MLModel.created_at.desc())
        ).first()
        production_id = str(production.id) if production else None
        production_value = (production.metrics or {}).get(metric_name) if production else None

    decision: Literal["Promote", "Reject", "Shadow-Test"]
    metric_deltas: dict[str, float] = {}
    if metric_name == "backtest_sharpe":
        decision = "Promote" if candidate_value > SHARPE_PASS_THRESHOLD else "Reject"
        if production_value is not None and candidate_value <= production_value:
            decision = "Reject"
        metric_deltas[metric_name] = candidate_value - (production_value or 0.0)
        confidence = min(
            1.0, max(0.0, (candidate_value - SHARPE_PASS_THRESHOLD) / SHARPE_PASS_THRESHOLD)
        )
    else:
        lower_is_better = metric_name in _LOWER_IS_BETTER
        if production_value is None:
            decision = "Promote"
            improvement = 0.0
        else:
            if lower_is_better:
                improvement = (production_value - candidate_value) / abs(production_value or 1e-9)
            else:
                improvement = (candidate_value - production_value) / abs(production_value or 1e-9)
            if improvement < 0:
                decision = "Reject"
            elif improvement >= PROMOTION_MARGIN:
                decision = "Promote"
            else:
                decision = "Shadow-Test"
        metric_deltas[metric_name] = candidate_value - (production_value or 0.0)
        confidence = (
            min(1.0, max(0.0, improvement / (2 * PROMOTION_MARGIN)))
            if production_value is not None
            else 0.5
        )

    comparison_report = _generate_report(
        candidate_id=candidate_id,
        production_id=production_id,
        decision=decision,
        metric_deltas=metric_deltas,
        confidence_score=confidence,
    )

    return {
        "model_evaluation_verdict": ModelEvaluationVerdict(
            decision=decision,
            candidate_ml_model_id=candidate_id,
            production_ml_model_id=production_id,
            metric_deltas=metric_deltas,
            confidence_score=confidence,
            comparison_report=comparison_report,
        )
    }
