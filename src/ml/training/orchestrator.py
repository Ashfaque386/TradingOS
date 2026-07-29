"""REL-008 E8.2: the single funnel every training trigger calls -- manual (`POST
/ml/models/train`), the weekly-scheduled job (E8.5), and drift-triggered retraining (E8.5) all
route through `run_training_job()`, differing only in `window_start`/`window_end`/
`trigger_reason`, not via separate code paths.

Single-symbol scope, stated honestly: Phase_5 §2's own named examples ("predict next 5-minute
return for RELIANCE") are per-symbol, and this release trains one model per (symbol, model_type,
task) combination -- `symbols` accepts a list for API-surface forward-compatibility, but only
`symbols[0]` is actually used; joint multi-symbol/cross-sectional modeling is not attempted here.
"""

import subprocess
from datetime import date
from pathlib import Path
from typing import Literal

import torch
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.ml.features.store import build_feature_frame, compute_training_data_hash
from src.ml.mlflow_client import get_tracking_uri, sync_mlflow_run_to_ml_models
from src.ml.serving.onnx_export import export_lightgbm_to_onnx, export_torch_to_onnx
from src.ml.training.lightgbm_runner import train_lightgbm
from src.ml.training.tft_runner import SEQ_LEN, train_tft
from src.ml.training.types import TrainingRunOutcome
from src.models.ml import MLModel


def _git_commit_hash() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=Path(__file__).parents[3]
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _export_to_onnx(
    model_type: Literal["LightGBM", "TFT-PyTorch"], outcome: TrainingRunOutcome
) -> str:
    """Real ONNX export, per DB-017's own schema comment for `artifact_path`
    (Phase_11_Database_Design.md: "`.onnx`/`.pkl` location") -- the ml_models row's artifact_path
    is a real, loadable ONNX file path, not an MLflow run URI. The MLflow-native model logged
    inside train_lightgbm()/train_tft() remains the lineage/registry record; this is the separate
    artifact E8.3's /predict endpoint actually serves."""
    onnx_root = get_settings().data_lake_root / "ml_artifacts"
    onnx_path = onnx_root / outcome.mlflow_run_id / "model.onnx"

    if model_type == "LightGBM":
        export_lightgbm_to_onnx(outcome.model, outcome.feature_columns, onnx_path)
    else:
        dummy_input = torch.zeros(1, SEQ_LEN, len(outcome.feature_columns))
        export_torch_to_onnx(outcome.model, dummy_input, onnx_path)

    return str(onnx_path)


def run_training_job(
    session: Session,
    *,
    model_type: Literal["LightGBM", "TFT-PyTorch"],
    task: Literal["classification", "regression"],
    symbols: list[str],
    window_start: date,
    window_end: date,
    trigger_reason: Literal["manual", "weekly_scheduled", "drift_triggered"] = "manual",
) -> MLModel:
    if not symbols:
        raise ValueError("symbols must be non-empty")
    symbol = symbols[0]

    get_tracking_uri()  # mlflow.set_tracking_uri() side effect
    lake_root = get_settings().data_lake_root / "ohlcv_daily"
    feature_df = build_feature_frame(symbol, window_start, window_end, lake_root=lake_root)
    training_data_hash = compute_training_data_hash(feature_df)
    git_commit_hash = _git_commit_hash()

    if model_type == "LightGBM":
        outcome = train_lightgbm(symbol=symbol, feature_df=feature_df, task=task)
    else:
        outcome = train_tft(symbol=symbol, feature_df=feature_df)
    artifact_path = _export_to_onnx(model_type, outcome)

    metrics_payload = {
        **outcome.metrics,
        "baseline_comparison": outcome.baseline_comparison,
        "training_window": {"start": window_start.isoformat(), "end": window_end.isoformat()},
        "trigger_reason": trigger_reason,
        "symbol": symbol,
        "task": task,
    }

    return sync_mlflow_run_to_ml_models(
        session,
        mlflow_run_id=outcome.mlflow_run_id,
        name=f"{model_type}_{task}_{symbol}",
        model_type=model_type,
        artifact_path=artifact_path,
        git_commit_hash=git_commit_hash,
        training_data_hash=training_data_hash,
        metrics=metrics_payload,
    )
