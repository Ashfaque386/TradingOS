"""REL-008 E8.2: real end-to-end LightGBM training against the real data lake and the real
MLflow tracking server (docker-compose.yml's `mlflow` service)."""

from datetime import date

import mlflow

from src.core.db import get_session
from src.ml.mlflow_client import get_tracking_uri
from src.ml.training.orchestrator import run_training_job


def test_run_training_job_produces_a_real_staging_model_and_a_real_mlflow_run() -> None:
    with get_session() as session:
        ml_model = run_training_job(
            session,
            model_type="LightGBM",
            task="classification",
            symbols=["RELIANCE"],
            window_start=date(2023, 7, 21),
            window_end=date(2024, 7, 19),
            trigger_reason="manual",
        )
        session.commit()

        assert ml_model.stage == "Staging"
        assert ml_model.model_type == "LightGBM"
        assert ml_model.mlflow_run_id
        assert ml_model.training_data_hash
        assert ml_model.metrics is not None
        assert "test_accuracy" in ml_model.metrics
        assert ml_model.metrics["baseline_comparison"]["baseline_momentum_accuracy"] is not None

    # git_commit_hash matches the real repo HEAD -- this codebase is a real git repo.
    import subprocess

    real_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    assert ml_model.git_commit_hash == real_head

    get_tracking_uri()
    run = mlflow.get_run(ml_model.mlflow_run_id)
    assert run.info.run_id == ml_model.mlflow_run_id
    assert "test_accuracy" in run.data.metrics
