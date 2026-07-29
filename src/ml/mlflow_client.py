"""REL-008: the bridge between MLflow's own registry (source of truth for run/param/metric
history) and the Postgres `ml_models` (DB-017) mirror row this app's own endpoints/agents query
directly, without hitting MLflow's HTTP API on every request.
"""

from typing import Any

import mlflow
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.models.ml import MLModel


def get_tracking_uri() -> str:
    uri = get_settings().mlflow_tracking_uri
    mlflow.set_tracking_uri(uri)
    return uri


def sync_mlflow_run_to_ml_models(
    session: Session,
    *,
    mlflow_run_id: str,
    name: str,
    model_type: str,
    artifact_path: str,
    git_commit_hash: str,
    training_data_hash: str,
    metrics: dict[str, Any],
) -> MLModel:
    """Creates the real `ml_models` row backing a just-completed MLflow run -- always starts at
    `stage="Staging"` (the model registry default, per Phase_5 §3); promotion to `Production` is
    a separate, always human/role-gated call (`POST /ml/models/{id}/promote`, never automatic)."""
    row = MLModel(
        name=name,
        model_type=model_type,
        mlflow_run_id=mlflow_run_id,
        stage="Staging",
        git_commit_hash=git_commit_hash,
        training_data_hash=training_data_hash,
        metrics=metrics,
        artifact_path=artifact_path,
    )
    session.add(row)
    session.flush()
    return row
