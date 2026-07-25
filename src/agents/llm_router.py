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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import litellm
import structlog
import yaml

from src.core import vault
from src.core.config import Settings, get_settings

logger = structlog.get_logger(__name__)

_tracing_configured = False


def _configure_tracing(settings: Settings) -> None:
    """Enables LiteLLM's built-in LangSmith callback (NFR-05 — 100% of LLM calls traced) once,
    only if LANGSMITH_API_KEY is configured; otherwise tracing is silently skipped."""
    global _tracing_configured
    if _tracing_configured or not settings.langsmith_api_key:
        return
    os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key)
    os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)
    litellm.success_callback.append("langsmith")
    litellm.failure_callback.append("langsmith")
    _tracing_configured = True


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
    return bool(resolve_api_key(provider, settings))


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


def complete(task_type: TaskType, messages: list[dict[str, str]], **kwargs: Any) -> Any:
    """Tries each configured provider in the task's fallback chain in order; returns the first
    successful litellm ModelResponse. Raises NoProviderAvailableError if every attempt fails
    (including the case where no provider in the chain has a configured key)."""
    settings = get_settings()
    _configure_tracing(settings)
    chain = build_fallback_chain(task_type, settings)
    if not chain:
        raise NoProviderAvailableError(f"no configured provider for task type '{task_type}'")

    last_error: Exception | None = None
    for pm in chain:
        try:
            response = litellm.completion(
                messages=messages, **_litellm_kwargs(pm, settings), **kwargs
            )
            logger.info(
                "llm_call_succeeded", task_type=task_type, provider=pm.provider, model=pm.model
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
            last_error = exc

    raise NoProviderAvailableError(
        f"all {len(chain)} configured provider(s) failed for task type '{task_type}'"
    ) from last_error
