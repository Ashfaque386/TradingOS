"""REL-008 E8.3: ONNX Runtime inference serving (Phase_5 §5's "Inference Pipeline"):

- "Serving: FastAPI endpoints wrapping ONNX Runtime for ultra-low latency inference (< 10ms)."
- "Fallback: If inference times out (> 50ms), the system falls back to a neutral, hardcoded
  baseline rule."

The `< 10ms` figure has no stated measurement methodology anywhere in the design corpus. This
module measures real wall-clock single-request latency via `time.perf_counter()` and always
returns the real number -- callers (tests, the /predict endpoint) report it honestly rather than
asserting it clears the target, since a single shared dev host is unlikely to hit it reliably.
"""

import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

import numpy as np
import onnxruntime

ONNX_LATENCY_TARGET_SECONDS = 0.010
ONNX_FALLBACK_TRIP_SECONDS = 0.050

# The hardcoded neutral fallback rule Phase_5 §5 specifies -- "0.5" for classification reads as
# "50/50, no signal", "0.0" for regression reads as "predict no move".
NEUTRAL_BASELINE_PREDICTION: dict[str, float] = {"classification": 0.5, "regression": 0.0}


@dataclass
class InferenceOutcome:
    prediction: float
    used_fallback: bool
    latency_seconds: float


@lru_cache(maxsize=32)
def load_onnx_session(artifact_path: str) -> onnxruntime.InferenceSession:
    return onnxruntime.InferenceSession(artifact_path, providers=["CPUExecutionProvider"])


def run_inference(
    session: onnxruntime.InferenceSession,
    feature_vector: dict[str, float],
    feature_order: list[str],
    task: Literal["classification", "regression"],
) -> InferenceOutcome:
    input_name = session.get_inputs()[0].name
    x = np.array([[feature_vector[c] for c in feature_order]], dtype=np.float32)

    start = time.perf_counter()
    outputs = session.run(None, {input_name: x})
    elapsed = time.perf_counter() - start

    if elapsed > ONNX_FALLBACK_TRIP_SECONDS:
        return InferenceOutcome(
            prediction=NEUTRAL_BASELINE_PREDICTION[task],
            used_fallback=True,
            latency_seconds=elapsed,
        )

    prediction = _extract_scalar_prediction(outputs, task)
    return InferenceOutcome(prediction=prediction, used_fallback=False, latency_seconds=elapsed)


def _extract_scalar_prediction(outputs: list[np.ndarray], task: str) -> float:
    """ONNX Runtime's output shape varies by exporter -- sklearn-API classifiers (LightGBM via
    onnxmltools) typically emit [labels, probabilities] as two separate outputs; a plain
    regression/torch export emits a single tensor. Handles both real shapes rather than assuming
    one."""
    if task == "classification" and len(outputs) > 1:
        # outputs[1] is typically a list of {class: probability} dicts (zipmap output) or a
        # [N, n_classes] probability array, depending on the exporter -- handle both.
        proba = outputs[1]
        if isinstance(proba, list):
            return float(proba[0][1]) if len(proba[0]) > 1 else float(proba[0][0])
        return float(np.asarray(proba)[0, -1])

    value = np.asarray(outputs[0]).reshape(-1)[0]
    return float(value)
