import time
from dataclasses import dataclass

import numpy as np
import pytest

from src.ml.serving.onnx_runtime_service import (
    NEUTRAL_BASELINE_PREDICTION,
    ONNX_FALLBACK_TRIP_SECONDS,
    run_inference,
)


@dataclass
class _FakeInput:
    name: str


class _FakeSession:
    """Implements just the two onnxruntime.InferenceSession methods run_inference() calls, so
    the fallback trip-wire can be tested without needing a real exported ONNX model on disk."""

    def __init__(self, output: list[np.ndarray], delay_seconds: float = 0.0) -> None:
        self._output = output
        self._delay_seconds = delay_seconds

    def get_inputs(self) -> list[_FakeInput]:
        return [_FakeInput(name="input")]

    def run(self, _output_names: object, _feed: dict[str, np.ndarray]) -> list[np.ndarray]:
        if self._delay_seconds:
            time.sleep(self._delay_seconds)
        return self._output


def test_fast_session_returns_real_prediction_without_fallback() -> None:
    session = _FakeSession(output=[np.array([[0.73]], dtype=np.float32)])

    outcome = run_inference(
        session, {"a": 1.0, "b": 2.0}, feature_order=["a", "b"], task="regression"
    )

    assert outcome.used_fallback is False
    assert outcome.prediction == pytest.approx(0.73)
    assert outcome.latency_seconds >= 0


def test_slow_session_trips_the_fallback_and_returns_the_neutral_baseline() -> None:
    session = _FakeSession(
        output=[np.array([[0.73]], dtype=np.float32)],
        delay_seconds=ONNX_FALLBACK_TRIP_SECONDS + 0.02,
    )

    outcome = run_inference(
        session, {"a": 1.0, "b": 2.0}, feature_order=["a", "b"], task="regression"
    )

    assert outcome.used_fallback is True
    assert outcome.prediction == NEUTRAL_BASELINE_PREDICTION["regression"]
    assert outcome.latency_seconds > ONNX_FALLBACK_TRIP_SECONDS


def test_classification_extracts_positive_class_probability() -> None:
    # Mirrors onnxmltools' typical [labels, probabilities] two-output shape for a classifier.
    session = _FakeSession(
        output=[np.array([1]), [{0: 0.2, 1: 0.8}]],
    )

    outcome = run_inference(session, {"a": 1.0}, feature_order=["a"], task="classification")

    assert outcome.used_fallback is False
    assert outcome.prediction == pytest.approx(0.8)
