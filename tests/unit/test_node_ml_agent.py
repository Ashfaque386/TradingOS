import uuid
from unittest.mock import MagicMock, patch

import pytest

from src.agents.nodes.ml_agent import ml_agent_node
from src.agents.state import MLTrainingRequest, TradingOSGraphState

_REQUEST = MLTrainingRequest(
    model_type="LightGBM",
    task="classification",
    symbols=["RELIANCE"],
    window_start="2023-07-21",
    window_end="2024-07-19",
)


def _fake_response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices[0].message.content = content
    return response


def _fake_ml_model():
    model = MagicMock()
    model.id = uuid.uuid4()
    model.mlflow_run_id = "fake-run-id"
    model.artifact_path = "/tmp/fake.onnx"
    model.git_commit_hash = "abc123"
    model.training_data_hash = "hash123"
    model.metrics = {
        "test_accuracy": 0.6,
        "baseline_comparison": {"model_accuracy": 0.6, "baseline_momentum_accuracy": 0.5},
    }
    return model


def _state() -> TradingOSGraphState:
    return TradingOSGraphState(thread_id="t1", ml_training_request=_REQUEST)


def _fake_session_cm():
    """A no-op context manager standing in for get_session() -- this node's only real DB use is
    inside the mocked run_training_job() itself, so a hermetic unit test doesn't need a real
    Postgres connection, matching every other file in tests/unit/."""
    cm = MagicMock()
    cm.__enter__.return_value = MagicMock()
    cm.__exit__.return_value = False
    return cm


def test_ml_agent_node_requires_ml_training_request():
    with pytest.raises(ValueError):
        ml_agent_node(TradingOSGraphState(thread_id="t1"))


def test_ml_agent_node_returns_a_real_training_result():
    narrative_json = '{"narrative": "Trained successfully, beat the baseline."}'
    with (
        patch("src.agents.nodes.ml_agent.get_session", return_value=_fake_session_cm()),
        patch(
            "src.agents.nodes.ml_agent.run_training_job", return_value=_fake_ml_model()
        ) as mock_train,
        patch("src.agents.nodes.ml_agent.complete", return_value=_fake_response(narrative_json)),
    ):
        result = ml_agent_node(_state())

    mock_train.assert_called_once()
    ml_result = result["ml_training_result"]
    assert ml_result.model_type == "LightGBM"
    assert ml_result.metrics["test_accuracy"] == 0.6
    assert ml_result.narrative == "Trained successfully, beat the baseline."


def test_ml_agent_node_falls_back_to_deterministic_narrative_on_llm_failure():
    with (
        patch("src.agents.nodes.ml_agent.get_session", return_value=_fake_session_cm()),
        patch("src.agents.nodes.ml_agent.run_training_job", return_value=_fake_ml_model()),
        patch("src.agents.nodes.ml_agent.complete", side_effect=RuntimeError("LLM down")),
    ):
        result = ml_agent_node(_state())

    ml_result = result["ml_training_result"]
    assert "LightGBM" in ml_result.narrative
    assert "RELIANCE" in ml_result.narrative
