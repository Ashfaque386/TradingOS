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

    # REL-010 E10.7: real, hand-maintained corporate-actions CSV (src/data/ingest/
    # corporate_actions.py's own docstring explains why this is a CSV, not a live NSE feed --
    # no official NSE corporate-actions API/CSV exists, confirmed via web search at
    # implementation time). Missing file is a real, honest no-op (CorporateActionsAdapter.fetch
    # returns []), not an error -- this dev environment has no seed data yet by default.
    corporate_actions_csv_path: Path = Path("/app/data/corporate_actions_seed.csv")

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

    # REL-015 E15.3 (GLH-06, SEC-039): the `minio` compose service, MinIO's real S3-compatible
    # API with Object Lock support -- see src/core/audit_archive.py for the WORM archive tier
    # built on top of this.
    audit_archive_s3_endpoint: str = "http://minio:9000"
    audit_archive_s3_access_key: str = "tradingos-minio-admin"
    audit_archive_s3_secret_key: str = "tradingos_minio_dev_password"
    audit_archive_s3_bucket: str = "audit-archive"

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

    # REL-009 (2026-07-30): the user enabled HuggingFace Pro billing and asked for huggingface to
    # replace local Ollama as the default provider for every task type (routing.yaml), with real
    # usage optimization added so a burst of calls can't silently exhaust the account's real
    # quota. `hf_max_tokens_per_call` bounds a single call's own cost (applied only when the
    # caller doesn't already pass its own `max_tokens`); `hf_daily_token_budget` is a soft,
    # locally-tracked UTC-daily cap (src/agents/llm_router.py's `_hf_usage_tracker`) -- once real
    # tracked usage reaches it, huggingface is treated as unconfigured for the rest of that day
    # and every task-type chain naturally falls through to its next configured provider (ollama
    # last).
    #
    # hf_daily_token_budget is a real, sourced calculation, not a guess -- confirmed via HF's own
    # docs (2026-07-30): the $9/month PRO subscription includes $2.00/month of real Inference
    # credit (not $9 -- usage beyond that $2 bills pay-as-you-go to the account's card), and the
    # real routing.yaml model (meta-llama/Llama-3.3-70B-Instruct) prices at ~$0.10/M input tokens
    # / $0.32/M output tokens via HF's Inference Providers. Per explicit user choice: hard-cap at
    # the $2/month free credit so real spend never exceeds it. Using the worst-case all-output
    # rate ($0.32/M) for safety: $2.00 / 30 days / $0.32 per M tokens ~= 208,000 tokens/day,
    # rounded down to 200,000 -- real usage is never charged more than this represents even if
    # the actual input/output mix skews toward the pricier output rate. Re-derive by hand if HF's
    # published PRO credit amount or this model's per-token pricing changes.
    hf_max_tokens_per_call: int = 1024
    hf_daily_token_budget: int = 200_000

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

    # REL-010 E10.2 (Notification/Omni-Channel Agent, AGT-022): OUTBOUND credentials -- distinct
    # from the inbound-only secrets directly above (those verify a request came from the real
    # platform; these let this app send a real message back). Vault-first via
    # src/core/vault.py::read_bot_token, same fail-open .env fallback. `discord_application_id`
    # is Discord's public application ID (not a secret -- needed to build the real
    # `/webhooks/{application_id}/{interaction_token}` follow-up URL).
    telegram_bot_token: str | None = None
    discord_application_id: str | None = None
    # REL-026: WhatsApp's outbound pair, same split as Discord above -- whatsapp_access_token is
    # the real secret (Vault-first via read_bot_token("whatsapp"), same as telegram_bot_token),
    # whatsapp_business_phone_number_id is a public identifier (needed to build the real
    # `/{phone_number_id}/messages` send URL), not a secret.
    whatsapp_access_token: str | None = None
    whatsapp_business_phone_number_id: str | None = None

    # REL-007 E7.6 (TLS, SEC-023/024). Gates src/agents/scheduler.py's APScheduler so the
    # sibling `app-tls` compose service (same image, HTTPS-only) doesn't double-fire the daily
    # research cycle alongside the primary `app` service.
    run_scheduler: bool = True

    # REL-008's `mlflow_tracking_uri` setting (and the whole ML/RL platform it supported) was
    # removed 2026-07-30, disabled pending a host resource upgrade -- see
    # Phase_5_Machine_Learning_Architecture.md's own status banner and
    # Phase_14_Master_Development_Roadmap.md's REL-008 section for why. Re-add when Phase 5 is
    # re-implemented.

    # REL-009 E9.4: `False` in every real deployment -- gates a single deliberately-unsafe,
    # test-only endpoint (src/api/main.py's `/_zap_test/reflect`) that exists purely to prove
    # the real OWASP ZAP CI job (scripts/run_zap_scan.sh) genuinely detects a real
    # reflected-input vulnerability, not just that it runs and reports zero findings (which
    # could mean "nothing found" or "not actually scanning," indistinguishable without this).
    # Set to `True` only inside that one CI job's own environment, never in dev/prod.
    zap_test_endpoint_enabled: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
