FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    # REL-008: LightGBM's Linux wheel dynamically links libgomp.so.1 (OpenMP), not present on
    # bare python:3.12-slim -- confirmed via a real ImportError without this.
    libgomp1 \
    # REL-008: src/ml/training/orchestrator.py shells out to `git rev-parse HEAD` for real
    # model-lineage tracking (Phase_5 §3) -- the repo's .git dir is bind-mounted into the
    # container (docker-compose.yml's `.:/app`), but the `git` binary itself isn't on slim.
    git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src
COPY tests ./tests
COPY alembic ./alembic
COPY alembic.ini ./

# Each new heavyweight dependency group installed as its own step first: pip resolves each
# small tree in isolation, so the main install below finds everything already satisfied instead
# of backtracking across the full project's much larger combined constraint set (fastapi +
# vectorbt + temporalio + optuna together made a plain single-step install take 15+ minutes --
# verified empirically while adding optuna in Phase 3 E3.3).
RUN pip install --no-cache-dir "optuna>=4.0"
RUN pip install --no-cache-dir \
    "opentelemetry-api>=1.27" \
    "opentelemetry-sdk>=1.27" \
    "opentelemetry-instrumentation-fastapi>=0.48b0" \
    "opentelemetry-instrumentation-httpx>=0.48b0" \
    "opentelemetry-exporter-otlp-proto-http>=1.27" \
    "prometheus-client>=0.21"
# REL-008 (Machine Learning Platform) -- same isolation reasoning as optuna/otel above, this is
# the single largest new dependency tree added to this project (torch/lightgbm/mlflow/onnx/
# gymnasium/stable-baselines3 together).
RUN pip install --no-cache-dir \
    "mlflow>=2.17" \
    "lightgbm>=4.5" \
    "torch>=2.5" \
    "onnx>=1.17" \
    "onnxruntime>=1.19" \
    "onnxmltools>=1.13" \
    "gymnasium>=0.29" \
    "stable-baselines3>=2.3" \
    "scipy>=1.14"
RUN pip install --no-cache-dir -e ".[dev]"

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
