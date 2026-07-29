"""Shared result type for every training runner (LightGBM, TFT, and — E8.4 — the RL policies),
kept in its own module to avoid a circular import between the individual runners and
orchestrator.py, which imports all of them."""

from dataclasses import dataclass
from typing import Any


@dataclass
class TrainingRunOutcome:
    mlflow_run_id: str
    model: Any  # the trained model/booster object -- caller (orchestrator/ONNX export) uses it
    metrics: dict[str, float]
    baseline_comparison: dict[str, float]
    feature_columns: list[str]
