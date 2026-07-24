FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
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
RUN pip install --no-cache-dir -e ".[dev]"

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
