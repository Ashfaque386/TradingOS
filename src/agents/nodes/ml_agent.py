"""ML Agent node (AGT-017, PMPT-017/040) -- REL-008 E8.6.

Unlike most nodes in this package, this one opens its own `get_session()` block: its entire
deterministic action *is* a real database write (a new `ml_models` row via
src/ml/training/orchestrator.py::run_training_job()), not a state output later materialized by
src/api/routers/agents.py's central `_execute_graph_run` persistence step -- there is no separate
"the write happens elsewhere" seam to defer to here, the training result only exists once it's
been written.

Same "LLM narrates a pre-computed, deterministic result; LLM failure never blocks the pipeline"
convention as every other node in this package (compliance.py, evaluator.py, deployment.py) --
which model gets trained, and its real metrics, come entirely from run_training_job(), never
from the LLM.
"""

import json
from datetime import date

import structlog

from src.agents.llm_router import complete
from src.agents.nodes.common import extract_json
from src.agents.prompt_registry import get_active_prompt
from src.agents.state import MLTrainingResult, TradingOSGraphState
from src.core.db import get_session
from src.ml.training.orchestrator import run_training_job

PROMPT_SLUG = "ml_agent"
TASK_PROMPT_SLUG = "ml_agent_task"
logger = structlog.get_logger(__name__)


def _generate_narrative(
    *,
    symbol: str,
    model_type: str,
    task: str,
    trigger_reason: str,
    metrics: dict[str, float],
    baseline: dict[str, float],
) -> str:
    try:
        system_prompt = get_active_prompt(PROMPT_SLUG)
        user_prompt = get_active_prompt(TASK_PROMPT_SLUG).format(
            symbol=symbol,
            model_type=model_type,
            task=task,
            trigger_reason=trigger_reason,
            metrics_summary=json.dumps(metrics),
            baseline_summary=json.dumps(baseline),
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
        logger.warning("ml_agent_narrative_fallback", error=str(exc))
        return (
            f"Trained a {model_type} {task} model for {symbol} ({trigger_reason}). "
            f"Metrics: {metrics}. Baseline comparison: {baseline}."
        )


def ml_agent_node(state: TradingOSGraphState) -> dict[str, object]:
    if state.ml_training_request is None:
        raise ValueError("ml_agent_node requires state.ml_training_request")
    request = state.ml_training_request

    with get_session() as session:
        ml_model = run_training_job(
            session,
            model_type=request.model_type,
            task=request.task,
            symbols=request.symbols,
            window_start=date.fromisoformat(request.window_start),
            window_end=date.fromisoformat(request.window_end),
            trigger_reason=request.trigger_reason,
        )
        session.commit()

        ml_model_metrics = ml_model.metrics or {}
        metrics = {k: v for k, v in ml_model_metrics.items() if isinstance(v, int | float)}
        baseline = ml_model_metrics.get("baseline_comparison", {})
        narrative = _generate_narrative(
            symbol=request.symbols[0],
            model_type=request.model_type,
            task=request.task,
            trigger_reason=request.trigger_reason,
            metrics=metrics,
            baseline=baseline,
        )

        result = MLTrainingResult(
            ml_model_id=str(ml_model.id),
            mlflow_run_id=ml_model.mlflow_run_id,
            model_type=request.model_type,
            metrics=metrics,
            baseline_comparison=baseline,
            artifact_path=ml_model.artifact_path,
            git_commit_hash=ml_model.git_commit_hash or "unknown",
            training_data_hash=ml_model.training_data_hash or "unknown",
            narrative=narrative,
        )

    return {"ml_training_result": result}
