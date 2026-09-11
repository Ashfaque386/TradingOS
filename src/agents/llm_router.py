"""Multi-provider LLM gateway (Phase 2 Epic E2.2).

Routes each call by task type through an ordered fallback chain of (provider, model) pairs,
per the tech research report's "Multi-LLM Routing via LiteLLM" recommendation. A provider with
no configured key is skipped, not treated as a failure. Which model handles which task type
lives in routing.yaml (loaded fresh per call, see load_routing_table()), not in this file —
edit that file to change routing without a code change or restart.

Each provider's API key is resolved Vault-first, falling back to `.env`-sourced Settings
(REL-002 E2.2 gap closure, 2026-07-25) — the same precedence already used for broker credentials
(src/brokers/factory.py, src/core/vault.py). `resolve_api_key()` is the single place that does
this; `is_configured()` and `_litellm_kwargs()` both go through it rather than reading Settings
fields directly.
"""

import os
import threading
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

import litellm
import structlog
import yaml

from src.core import vault
from src.core.config import Settings, get_settings
from src.observability.metrics import HF_TOKENS_USED_TODAY

logger = structlog.get_logger(__name__)

_tracing_configured = False

# REL-009 E9.2: LiteLLM's LangsmithLogger only starts its periodic background-flush task when
# called from a thread that already has a running asyncio event loop (verified empirically --
# `_start_periodic_flush_task` no-ops otherwise, logging "no running event loop, skipping").
# Every real caller of complete() in this codebase runs inside `_execute_graph_run`'s plain
# `threading.Thread` (src/api/routers/agents.py), which has no event loop of its own -- without
# this, every trace sits in LiteLLM's in-memory queue forever and 0% of calls actually reach
# LangSmith, silently, despite the callback being "configured". LANGSMITH_BATCH_SIZE=1 makes
# every single event trigger an immediate, synchronous send instead of waiting on that dead
# periodic task -- confirmed via a real call + a real langsmith.Client().read_run() lookup.
_LANGSMITH_BATCH_SIZE = "1"

# Set by complete() on every call where tracing is configured (the same UUID handed to LiteLLM
# as the LangSmith run's `id`), read+cleared by _execute_graph_run after each graph node so the
# resulting AgentRun row can be tagged with its real trace URL. A ContextVar (not a plain module
# global) so concurrent graph runs on different threads never see each other's run id.
_last_langsmith_run_id: ContextVar[str | None] = ContextVar("_last_langsmith_run_id", default=None)


def _configure_tracing(settings: Settings) -> None:
    """Enables LiteLLM's built-in LangSmith callback (NFR-05 — 100% of LLM calls traced) once,
    only if LANGSMITH_API_KEY is configured; otherwise tracing is silently skipped."""
    global _tracing_configured
    if _tracing_configured or not settings.langsmith_api_key:
        return
    os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key)
    os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)
    os.environ.setdefault("LANGSMITH_BATCH_SIZE", _LANGSMITH_BATCH_SIZE)
    litellm.success_callback.append("langsmith")
    litellm.failure_callback.append("langsmith")
    _tracing_configured = True


def pop_last_langsmith_run_id() -> str | None:
    """Reads and clears the run id complete() last set (see _last_langsmith_run_id's docstring)
    -- called once per graph node by _execute_graph_run. Returns None both when tracing isn't
    configured and when the node made no LLM call at all; callers can't and don't need to tell
    the two apart."""
    run_id = _last_langsmith_run_id.get()
    _last_langsmith_run_id.set(None)
    return run_id


def fetch_langsmith_trace_url(
    run_id: str, *, attempts: int = 3, delay_seconds: float = 1.0
) -> str | None:
    """Real lookup against the LangSmith API for the URL of a just-completed run. Bounded
    retries since the trace was just POSTed synchronously moments earlier and LangSmith's own
    indexing can lag briefly. Fails soft (returns None, logs a warning) on any error -- tracing
    is an observability concern and must never break the agent pipeline it's observing, same
    principle as every LLM-narrative fallback elsewhere in this codebase."""
    try:
        from langsmith import Client
    except ImportError:  # pragma: no cover -- langsmith is an installed transitive dep today
        return None

    settings = get_settings()
    if not settings.langsmith_api_key:
        return None

    client = Client(api_key=settings.langsmith_api_key)
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            run = client.read_run(run_id)
            return str(run.url).split("?", 1)[0]  # strip ?trace_id=&start_time= -- still a
            # fully valid, clickable trace URL, and comfortably under AgentRun.langsmith_trace_url's
            # 255-char column limit regardless of org/project UUID length.
        except Exception as exc:  # noqa: BLE001 - see docstring: never raise out of this helper
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(delay_seconds)
    logger.warning("langsmith_trace_url_fetch_failed", run_id=run_id, error=str(last_error))
    return None


class _HFUsageTracker:
    """Real, in-process, single-day token-usage counter for the huggingface provider (REL-009,
    2026-07-30: keep real usage under the account's real HF Pro-tier quota). Module-level
    singleton -- matches this being a single-process FastAPI service, same justification as
    src/engine/risk/kill_switch_service.py's own module-level state: there is exactly one real
    usage budget for the whole running app, not one per request or per thread. Resets at UTC day
    rollover, not a rolling 24h window -- simple, predictable, and matches how most provider
    dashboards report daily usage."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._day: date = datetime.now(UTC).date()
        self._tokens_used = 0

    def _reset_if_new_day_locked(self) -> None:
        today = datetime.now(UTC).date()
        if today != self._day:
            self._day = today
            self._tokens_used = 0
            HF_TOKENS_USED_TODAY.set(0)

    def record(self, tokens: int) -> None:
        with self._lock:
            self._reset_if_new_day_locked()
            self._tokens_used += max(tokens, 0)
            HF_TOKENS_USED_TODAY.set(self._tokens_used)

    def has_budget(self, daily_budget: int) -> bool:
        with self._lock:
            self._reset_if_new_day_locked()
            return self._tokens_used < daily_budget

    def tokens_used_today(self) -> int:
        with self._lock:
            self._reset_if_new_day_locked()
            return self._tokens_used


_hf_usage_tracker = _HFUsageTracker()


class _ProviderFailureTracker:
    """T105 (research finding, brief §84): a real, process-local record of each provider's most
    recent `complete()` failure -- the same lock-guarded pattern as `_HFUsageTracker` above, since
    many org task-engine worker threads call `complete()` concurrently. `GET /providers/health`
    (provider_models.py) uses this to report a provider `unreachable` from real recent traffic,
    not just "a key happens to be configured" -- a configured-but-broken key (confirmed live this
    session: HuggingFace credits depleted, OpenCode no payment method) previously showed
    `connected` regardless of whether it actually worked."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_failure_at: dict[str, datetime] = {}
        # Whether this provider's most recent successful call was itself reached only after an
        # earlier provider in that call's chain failed first -- distinct from `_last_failure_at`
        # (this provider failing) since `in_fallback` describes the *chain's* behaviour around
        # this provider, not this provider's own health.
        self._last_success_was_fallback: dict[str, bool] = {}

    def record_failure(self, provider: str) -> None:
        with self._lock:
            self._last_failure_at[provider] = datetime.now(UTC)

    def record_success(self, provider: str, *, fell_back: bool) -> None:
        with self._lock:
            self._last_failure_at.pop(provider, None)
            self._last_success_was_fallback[provider] = fell_back

    def snapshot(self) -> dict[str, datetime]:
        with self._lock:
            return dict(self._last_failure_at)

    def fallback_snapshot(self) -> dict[str, bool]:
        with self._lock:
            return dict(self._last_success_was_fallback)


_provider_failures = _ProviderFailureTracker()


def get_provider_failure_status() -> dict[str, datetime]:
    """Every provider's most recent real `complete()` failure timestamp, if any -- read by
    `GET /providers/health`."""
    return _provider_failures.snapshot()


def get_provider_fallback_status() -> dict[str, bool]:
    """Whether each provider's most recent successful `complete()` call was itself reached via
    fallback (an earlier provider in that call's chain failed first) -- read by
    `GET /providers/health`'s `in_fallback` field."""
    return _provider_failures.fallback_snapshot()


# T105: the (provider, model, whether the chain fell back) `complete()` last actually used --
# read+cleared by the org layer's LLM-calling handlers (agent_invoker.py) right after their call,
# same ContextVar-per-call pattern as `_last_langsmith_run_id` above (thread/task-local, so
# concurrent callers never see each other's result).
@dataclass(frozen=True)
class LastCallInfo:
    provider: str
    model: str
    fell_back: bool
    failed_providers: list[str]


_last_call_info: ContextVar["LastCallInfo | None"] = ContextVar("_last_call_info", default=None)


def pop_last_call_info() -> "LastCallInfo | None":
    """Reads and clears the routing outcome `complete()` last recorded. `None` when the caller
    made no `complete()` call at all; callers can't and don't need to tell that apart from a
    call that somehow left nothing set."""
    info = _last_call_info.get()
    _last_call_info.set(None)
    return info


TaskType = Literal["coding", "orchestration", "sentiment", "research", "chat"]

PROVIDERS = ("ollama", "openai", "anthropic", "deepseek", "gemini", "huggingface", "opencode")

# OpenCode Zen (opencode.ai) — a curated, pay-per-use LLM gateway distinct from OpenRouter.
# OpenAI-compatible API; model IDs are plain (no provider prefix — verified live against
# GET /v1/models, e.g. "gpt-5.4-nano", "claude-opus-4-8", "gemini-3.5-flash-lite"), so litellm
# is pointed at it via api_base override on the "openai/" custom-provider path rather than a
# dedicated litellm provider prefix.
OPENCODE_ZEN_BASE_URL = "https://opencode.ai/zen/v1"


@dataclass(frozen=True)
class ProviderModel:
    provider: str
    model: str


ROUTING_CONFIG_PATH = Path(__file__).parent / "routing.yaml"


def load_routing_table() -> dict[str, list[ProviderModel]]:
    """Reads routing.yaml fresh on every call (no import-time caching) so editing which model
    handles a task type takes effect on the next agent call -- no app restart needed, same
    pattern as src/agents/prompt_registry.py."""
    with ROUTING_CONFIG_PATH.open(encoding="utf-8") as f:
        raw: dict[str, list[dict[str, str]]] = yaml.safe_load(f)
    return {
        task_type: [ProviderModel(entry["provider"], entry["model"]) for entry in chain]
        for task_type, chain in raw.items()
    }


class NoProviderAvailableError(RuntimeError):
    pass


def _settings_api_key(provider: str, settings: Settings) -> str | None:
    return {
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
        "deepseek": settings.deepseek_api_key,
        "gemini": settings.gemini_api_key,
        "huggingface": settings.hf_token,
        "opencode": settings.opencode_api_key,
    }[provider]


def resolve_api_key(provider: str, settings: Settings) -> str | None:
    """Vault-first, falling back to `.env`-sourced Settings — same precedence as broker
    credentials (src/brokers/factory.py). `provider="ollama"` never has a key (returns None)."""
    if provider == "ollama":
        return None
    stored = vault.read_llm_provider_key(provider, settings=settings)
    if stored:
        return stored
    return _settings_api_key(provider, settings)


def is_configured(provider: str, settings: Settings) -> bool:
    if provider == "ollama":
        return True
    if not resolve_api_key(provider, settings):
        return False
    if provider == "huggingface" and not _hf_usage_tracker.has_budget(
        settings.hf_daily_token_budget
    ):
        # Real usage-optimization guard (REL-009, 2026-07-30): once today's real tracked usage
        # hits the configured daily budget, huggingface is treated as unconfigured for the rest
        # of the day -- every task-type chain in routing.yaml already has huggingface followed by
        # further fallbacks (ollama last), so this naturally and safely falls through to those
        # rather than burning real quota into a hard provider error.
        logger.warning(
            "huggingface_daily_token_budget_exhausted",
            tokens_used_today=_hf_usage_tracker.tokens_used_today(),
            daily_budget=settings.hf_daily_token_budget,
        )
        return False
    return True


def _litellm_kwargs(pm: ProviderModel, settings: Settings) -> dict[str, Any]:
    if pm.provider == "ollama":
        return {"model": f"ollama/{pm.model}", "api_base": settings.ollama_base_url}
    api_key = resolve_api_key(pm.provider, settings)
    if pm.provider == "openai":
        return {"model": f"openai/{pm.model}", "api_key": api_key}
    if pm.provider == "anthropic":
        return {"model": f"anthropic/{pm.model}", "api_key": api_key}
    if pm.provider == "deepseek":
        return {"model": f"deepseek/{pm.model}", "api_key": api_key}
    if pm.provider == "gemini":
        return {"model": f"gemini/{pm.model}", "api_key": api_key}
    if pm.provider == "huggingface":
        return {"model": f"huggingface/{pm.model}", "api_key": api_key}
    if pm.provider == "opencode":
        return {
            "model": f"openai/{pm.model}",
            "api_base": OPENCODE_ZEN_BASE_URL,
            "api_key": api_key,
        }
    raise ValueError(f"unknown provider: {pm.provider}")


def build_fallback_chain(
    task_type: TaskType, settings: Settings | None = None
) -> list[ProviderModel]:
    settings = settings or get_settings()
    routing_table = load_routing_table()
    return [pm for pm in routing_table[task_type] if is_configured(pm.provider, settings)]


def complete(
    task_type: TaskType,
    messages: list[dict[str, str]],
    *,
    agent_name: str | None = None,
    **kwargs: Any,
) -> Any:
    """Tries each configured provider in the task's fallback chain in order; returns the first
    successful litellm ModelResponse. Raises NoProviderAvailableError if every attempt fails
    (including the case where no provider in the chain has a configured key).

    US6 (FR-104, SC-010): when ``agent_name`` names an agent whose ``AgentConfig`` is ``CUSTOM``
    with a currently-valid ``(provider, model)`` pair, that pair is prepended as the chain head.
    ``agent_name=None`` (or an ``AUTO`` / deterministic agent) leaves the chain byte-for-byte
    identical to the pre-feature behaviour.
    """
    settings = get_settings()
    _configure_tracing(settings)
    chain = build_fallback_chain(task_type, settings)

    if agent_name is not None:
        from src.orchestration.agent_config import resolve as _resolve_agent_pair

        pair = _resolve_agent_pair(agent_name, task_type)
        if pair is not None:
            head = ProviderModel(pair[0], pair[1])
            chain = [head, *[pm for pm in chain if pm != head]]

    if not chain:
        raise NoProviderAvailableError(f"no configured provider for task type '{task_type}'")

    run_id = str(uuid.uuid4())
    if settings.langsmith_api_key:
        metadata = kwargs.pop("metadata", {})
        metadata.setdefault("id", run_id)
        kwargs["metadata"] = metadata

    last_error: Exception | None = None
    failed_providers: list[str] = []
    for pm in chain:
        call_kwargs = dict(kwargs)
        # spec 001-ceo-led-trading-org T018 / audit AR-2: a hard per-call wall-clock cap so an
        # unresponsive provider cannot hang a worker thread indefinitely (the "zombie AgentRun"
        # pattern). Caller-supplied `timeout` still wins.
        call_kwargs.setdefault("timeout", settings.llm_call_timeout_seconds)
        if pm.provider == "huggingface":
            # Real usage-optimization guard (REL-009, 2026-07-30): caps a single call's own cost
            # unless the caller already asked for a specific max_tokens -- prevents one
            # unexpectedly long generation from eating a disproportionate chunk of the real daily
            # budget checked in is_configured() above.
            call_kwargs.setdefault("max_tokens", settings.hf_max_tokens_per_call)
        try:
            response = litellm.completion(
                messages=messages, **_litellm_kwargs(pm, settings), **call_kwargs
            )
            logger.info(
                "llm_call_succeeded", task_type=task_type, provider=pm.provider, model=pm.model
            )
            if pm.provider == "huggingface":
                usage = getattr(response, "usage", None)
                total_tokens = getattr(usage, "total_tokens", None) if usage else None
                if isinstance(total_tokens, int):
                    _hf_usage_tracker.record(total_tokens)
            if settings.langsmith_api_key:
                _last_langsmith_run_id.set(run_id)
            _provider_failures.record_success(pm.provider, fell_back=bool(failed_providers))
            _last_call_info.set(
                LastCallInfo(
                    provider=pm.provider,
                    model=pm.model,
                    fell_back=bool(failed_providers),
                    failed_providers=list(failed_providers),
                )
            )
            return response
        except Exception as exc:  # noqa: BLE001 - deliberately broad: fall through to next provider
            logger.warning(
                "llm_call_failed",
                task_type=task_type,
                provider=pm.provider,
                model=pm.model,
                error=str(exc),
            )
            _provider_failures.record_failure(pm.provider)
            failed_providers.append(pm.provider)
            last_error = exc

    raise NoProviderAvailableError(
        f"all {len(chain)} configured provider(s) failed for task type '{task_type}'"
    ) from last_error
