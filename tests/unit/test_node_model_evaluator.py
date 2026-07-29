from unittest.mock import MagicMock, patch

import pytest

from src.agents.nodes.model_evaluator import model_evaluator_node
from src.agents.state import MLTrainingResult, RLTrainingResult, TradingOSGraphState

_ML_RESULT = MLTrainingResult(
    ml_model_id="candidate-1",
    mlflow_run_id="run-1",
    model_type="LightGBM",
    metrics={"test_accuracy": 0.65},
    baseline_comparison={"baseline_momentum_accuracy": 0.5},
    artifact_path="/tmp/fake.onnx",
    git_commit_hash="abc123",
    training_data_hash="hash123",
    narrative="Trained.",
)

_RL_RESULT = RLTrainingResult(
    ml_model_id="candidate-rl-1",
    mlflow_run_id="run-rl-1",
    algorithm="PPO",
    reward_mean_by_seed={"1": 1.0},
    reward_variance_cv=0.1,
    stability_passed=True,
    backtest_sharpe=2.0,
    artifact_path="/tmp/fake_policy.zip",
    narrative="Trained RL.",
)


def _fake_response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices[0].message.content = content
    return response


def _session_cm_with_production(production):
    session = MagicMock()
    session.scalars.return_value.first.return_value = production
    cm = MagicMock()
    cm.__enter__.return_value = session
    cm.__exit__.return_value = False
    return cm


def test_model_evaluator_node_requires_a_candidate_result():
    with pytest.raises(ValueError):
        model_evaluator_node(TradingOSGraphState(thread_id="t1"))


def test_model_evaluator_node_promotes_a_first_ever_model_with_no_production():
    report_json = '{"comparison_report": "No prior Production model; candidate looks solid."}'
    with (
        patch(
            "src.agents.nodes.model_evaluator.get_session",
            return_value=_session_cm_with_production(None),
        ),
        patch(
            "src.agents.nodes.model_evaluator.complete", return_value=_fake_response(report_json)
        ),
    ):
        result = model_evaluator_node(
            TradingOSGraphState(thread_id="t1", ml_training_result=_ML_RESULT)
        )

    verdict = result["model_evaluation_verdict"]
    assert verdict.decision == "Promote"
    assert verdict.production_ml_model_id is None
    assert verdict.candidate_ml_model_id == "candidate-1"


def test_model_evaluator_node_rejects_a_worse_candidate():
    production = MagicMock()
    production.id = "prod-1"
    production.metrics = {"test_accuracy": 0.80}  # candidate's 0.65 is worse
    report_json = '{"comparison_report": "Candidate underperforms Production."}'
    with (
        patch(
            "src.agents.nodes.model_evaluator.get_session",
            return_value=_session_cm_with_production(production),
        ),
        patch(
            "src.agents.nodes.model_evaluator.complete", return_value=_fake_response(report_json)
        ),
    ):
        result = model_evaluator_node(
            TradingOSGraphState(thread_id="t1", ml_training_result=_ML_RESULT)
        )

    verdict = result["model_evaluation_verdict"]
    assert verdict.decision == "Reject"


def test_model_evaluator_node_shadow_tests_a_marginal_improvement():
    production = MagicMock()
    production.id = "prod-1"
    production.metrics = {"test_accuracy": 0.64}  # candidate's 0.65 beats it, but by < 5%
    report_json = '{"comparison_report": "Marginal improvement, route to shadow testing."}'
    with (
        patch(
            "src.agents.nodes.model_evaluator.get_session",
            return_value=_session_cm_with_production(production),
        ),
        patch(
            "src.agents.nodes.model_evaluator.complete", return_value=_fake_response(report_json)
        ),
    ):
        result = model_evaluator_node(
            TradingOSGraphState(thread_id="t1", ml_training_result=_ML_RESULT)
        )

    verdict = result["model_evaluation_verdict"]
    assert verdict.decision == "Shadow-Test"


def test_model_evaluator_node_handles_rl_candidates_via_sharpe_threshold():
    report_json = '{"comparison_report": "RL policy clears the Sharpe bar."}'
    with (
        patch(
            "src.agents.nodes.model_evaluator.get_session",
            return_value=_session_cm_with_production(None),
        ),
        patch(
            "src.agents.nodes.model_evaluator.complete", return_value=_fake_response(report_json)
        ),
    ):
        result = model_evaluator_node(
            TradingOSGraphState(thread_id="t1", rl_training_result=_RL_RESULT)
        )

    verdict = result["model_evaluation_verdict"]
    assert verdict.decision == "Promote"  # backtest_sharpe=2.0 > SHARPE_PASS_THRESHOLD=1.5


def test_model_evaluator_node_falls_back_to_deterministic_report_on_llm_failure():
    with (
        patch(
            "src.agents.nodes.model_evaluator.get_session",
            return_value=_session_cm_with_production(None),
        ),
        patch("src.agents.nodes.model_evaluator.complete", side_effect=RuntimeError("LLM down")),
    ):
        result = model_evaluator_node(
            TradingOSGraphState(thread_id="t1", ml_training_result=_ML_RESULT)
        )

    verdict = result["model_evaluation_verdict"]
    assert "Decision:" in verdict.comparison_report
