from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Defaults assume the app runs inside docker-compose (service hostnames, not localhost) —
    # see docker-compose.yml `app` service. All development runs in Docker; nothing local.
    database_url: str = (
        "postgresql+psycopg://tradingos:tradingos_dev_password@postgres:5432/tradingos"
    )
    qdrant_url: str = "http://qdrant:6333"
    redis_url: str = "redis://redis:6379/0"

    # Real single-node Temporal server (Phase 3 E3.3 Monte Carlo workflow) -- see
    # docker-compose.yml `temporal` service (`temporal server start-dev`). Distributing
    # simulation runs across a Kubernetes worker pool (Phase_3_Low_Level_Design.md §7) is
    # deferred past Phase 3; a single node is sufficient for a 10,000-path Monte Carlo run.
    temporal_address: str = "temporal:7233"
    temporal_task_queue: str = "tradingos-engine"

    data_lake_root: Path = Path("/app/data/lake")

    # DEPRECATED as of REL-007 E7.2: JWTs are now signed/verified via Vault's Transit engine
    # (src/core/vault_transit.py), not this static secret. Nothing reads these two fields
    # anymore -- kept only as a historical record of the pre-Transit scheme, deliberately not
    # wired up as a fallback (see src/core/security.py's module docstring for why).
    jwt_secret_key: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"

    # Local dev Vault (Phase 4 E4.1, see docker-compose.yml's `vault` service and
    # src/core/vault.py). `vault_addr` unset/unreachable means broker credentials fall back to
    # the plain settings fields below -- Vault is additive here, not a hard requirement, unlike
    # the fail-closed production posture Phase_12_Security_Design.md SEC-020 specifies.
    vault_addr: str | None = "http://vault:8200"
    vault_token: str | None = "dev-only-root-token"

    # LLM providers (Phase 2 E2.2 — see Phase_14_Master_Development_Roadmap.md §3.2).
    # Ollama always runs (local, no key). Every cloud provider is optional (`| None`) so an
    # unconfigured provider is simply skipped by src/agents/llm_router.py's fallback chains
    # rather than failing app startup. Dev-only: read straight from .env; production routes
    # through Vault instead (see Phase_12_Security_Design.md, and BROKER_CREDENTIALS in
    # Phase_11_Database_Design.md §2.2 for the pointer-only shape to converge toward).
    ollama_base_url: str = "http://host.docker.internal:11434"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    deepseek_api_key: str | None = None
    gemini_api_key: str | None = None
    hf_token: str | None = None
    opencode_api_key: str | None = None

    # LLM call tracing (Phase 2 E2.2, NFR-05 — 100% of LLM calls traced). Optional like the
    # providers above: unset means tracing is simply skipped, not an error.
    langsmith_api_key: str | None = None
    langsmith_project: str = "tradingos"

    # Embedding provider for the Qdrant RAG pipeline (Phase 2 E2.4 — see src/memory/embeddings.py).
    # A settings toggle, not a hardcoded choice: switching to huggingface/local/openai/gemini
    # once that provider's key is configured (and billing/quota allows it) is a `.env` change.
    # Each provider has a different vector dimension — changing this requires re-running
    # src/memory/collections.py's bootstrap with recreate_if_dim_mismatch=True.
    embedding_provider: Literal["ollama", "huggingface", "local", "openai", "gemini"] = "ollama"

    # Broker adapters (Phase 4 E4.1 — see src/brokers/). Upstox uses OAuth2: api_key/api_secret
    # are the app's Client ID/Secret from the developer portal; access_token is obtained via a
    # manual, interactive login (https://api.upstox.com/v2/login/authorization/dialog) and
    # expires daily at 3:30 AM IST -- there is no refresh token, so it must be re-generated and
    # re-pasted into .env each trading day until Vault-issued short-lived tokens land (E4.1).
    # `upstox_use_sandbox` defaults to True deliberately: sandbox (https://sandbox.upstox.com)
    # "closely emulates the real API with no risk" per Upstox's own docs, so real order-routing
    # code can be built and tested end-to-end without ever touching the live production host
    # (https://api.upstox.com / https://api-hft.upstox.com) or risking real funds. Flipping this
    # to False is a deliberate, explicit act, never a default.
    upstox_api_key: str | None = None
    upstox_api_secret: str | None = None
    upstox_redirect_uri: str | None = None
    upstox_access_token: str | None = None
    upstox_use_sandbox: bool = True

    # Zerodha Kite Connect (Phase 4 E4.1, primary executor per Phase_6_Trading_Engine_Design.md
    # §6). Also OAuth-like but with Kite's own vocabulary: after logging in via
    # https://kite.zerodha.com/connect/login?api_key=<api_key>&v=3, Zerodha redirects to
    # redirect_uri with a `request_token` (not a `code`); that gets exchanged for access_token
    # via POST https://api.kite.trade/session/token, authenticated with a checksum = SHA-256(
    # api_key + request_token + api_secret). The token expires daily (~6 AM IST) -- same
    # re-generate-each-trading-day story as Upstox, no refresh token.
    # Unlike Upstox, Kite Connect has no documented risk-free sandbox mode -- a "Connect" app is
    # real production API access (paid, 500 free trial credits/30 days). Real integration
    # tests against it need read-only calls or explicit paper-trading safeguards, not a
    # `use_sandbox` flag like Upstox's.
    zerodha_api_key: str | None = None
    zerodha_api_secret: str | None = None
    zerodha_redirect_uri: str | None = None
    zerodha_access_token: str | None = None

    # OpenTelemetry distributed tracing (Phase 4 E4.2, Phase_8_DevOps_Architecture.md §5).
    # Optional like the LLM providers above: real trace context is still created/propagated
    # across FastAPI/httpx/manual spans with no exporter configured (spans just aren't shipped
    # anywhere) -- unset means "trace locally but don't export", not "tracing is broken".
    otel_exporter_otlp_endpoint: str | None = None
    otel_service_name: str = "tradingos-api"

    # Prometheus WS-latency alerting (Phase 4 E4.2, Phase_9_Master_Implementation_Guide.md §5
    # Risk Register: "Prometheus alerts if WebSocket latency > 100ms. If triggered, the system
    # pauses live trading until synced.").
    ws_latency_pause_threshold_seconds: float = 0.1

    # REL-007 E7.7 (webhook signature verification, SEC-025..028). Vault-first (see
    # src/core/vault.py::read_webhook_secret), same fail-open .env fallback pattern as broker
    # credentials/LLM provider keys above -- these are optional so app startup never fails just
    # because no bot is registered yet in this dev environment.
    telegram_webhook_secret: str | None = None
    discord_public_key: str | None = None
    whatsapp_app_secret: str | None = None
    whatsapp_verify_token: str | None = None

    # REL-007 E7.6 (TLS, SEC-023/024). Gates src/agents/scheduler.py's APScheduler so the
    # sibling `app-tls` compose service (same image, HTTPS-only) doesn't double-fire the daily
    # research cycle alongside the primary `app` service.
    run_scheduler: bool = True

    # REL-008 (MLflow tracking server -- see docker-compose.yml's `mlflow` service). A separate
    # Postgres *database* (not a schema in `tradingos`) is its backend store, and the existing
    # `data_lake` named volume doubles as its artifact root (no object storage exists in this dev
    # stack) -- see scripts/setup_mlflow_database.py for the one-time DB-creation step.
    mlflow_tracking_uri: str = "http://mlflow:5000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
