FROM python:3.12-slim

WORKDIR /app

# REL-008's `libgomp1` (LightGBM's OpenMP link) and `git` (model-lineage `git rev-parse HEAD`)
# apt packages were removed 2026-07-30 alongside the ML/RL platform they existed for -- see
# Phase_5_Machine_Learning_Architecture.md's own status banner. Re-add if Phase 5 comes back.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# REL-009 E9.3: python:3.12-slim's bundled pip (25.0.1) has 6 real, known CVEs (found by this
# release's own new `pip-audit` CI gate) -- fixed for real by upgrading, not suppressed. Placed
# before the source COPY steps below so ordinary source-only rebuilds don't re-trigger it.
RUN pip install --no-cache-dir --upgrade "pip>=26.1.2"

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
# REL-008's ML/RL platform pip-install step (mlflow/lightgbm/torch/onnx/onnxruntime/onnxmltools/
# gymnasium/stable-baselines3/scipy -- by far the largest dependency tree in this image) was
# removed 2026-07-30, disabled pending a host resource upgrade -- see
# Phase_5_Machine_Learning_Architecture.md's own status banner.
#
# `sentence-transformers` (kept -- REL-005 local embeddings, unrelated to Phase 5) pulls in
# `torch` as its own hard dependency regardless, and pip's default index resolves the CUDA-
# enabled build, which drags in the entire nvidia-cu13* wheel family (cublas/cudnn/cufft/
# cusolver/triton/...) even though this host has no GPU -- confirmed for real: a first build
# without this step landed torch-2.13.0 plus ~15 nvidia-cu13* packages, an 11.1GB image.
# Installing the CPU-only wheel explicitly, before the main install below resolves
# sentence-transformers' own torch requirement, makes pip find it already satisfied and skip
# the CUDA build entirely -- the real, direct source of most of this image's remaining size.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch
RUN pip install --no-cache-dir -e ".[dev]"

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
