"""REL-008 E8.3: real end-to-end ONNX serving -- train a real LightGBM model on real RELIANCE
data, it exports to a real ONNX file (orchestrator.py's _export_to_onnx), then a real
POST /ml/models/{id}/predict call loads that file and serves a real inference.

Per the honest-measurement decision: this test asserts `latency_ms` is a positive, finite float
and explicitly does NOT assert it clears the design doc's <10ms target -- this shared dev host is
unlikely to hit that reliably, and the real measured number is reported either way.
"""

import math
from datetime import date

from fastapi.testclient import TestClient

from src.api.main import app
from src.core.db import get_session
from src.core.security import ROLE_SYSTEM_ADMINISTRATOR
from src.ml.training.orchestrator import run_training_job
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)


def test_train_export_and_serve_a_real_prediction_with_honestly_measured_latency():
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
        model_id = ml_model.id

    admin_id, admin_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.post(
            f"/api/v1/ml/models/{model_id}/predict",
            json={"symbol": "RELIANCE", "as_of_date": "2024-07-15"},
            headers=auth_header(admin_token),
        )
        assert response.status_code == 200
        body = response.json()

        assert isinstance(body["prediction"], float)
        assert math.isfinite(body["prediction"])
        assert isinstance(body["latency_ms"], float)
        assert body["latency_ms"] > 0
        assert math.isfinite(body["latency_ms"])
        # Explicitly NOT asserting body["latency_ms"] < 10 -- honest measurement, not a fabricated
        # pass. The real number is whatever this shared dev host actually produced.
        assert body["stage"] == "Staging"
    finally:
        cleanup_user(admin_id)
