"""LLM provider / model catalogue + health (spec T079/T105, contracts/rest-api.md, FR-105/110).

``GET /api/v1/providers`` lists only providers that are actually configured (a real key present
via Vault or settings) with the models ``routing.yaml`` references for them. ``GET /health``
reports **real signals only** (constitution VI): a provider is ``unreachable`` when it has no
configured key OR its most recent real `complete()` call attempt failed within
``PROVIDER_HEALTH_FAILURE_WINDOW`` (T105 -- a configured-but-broken key, e.g. depleted credits or
no payment method, previously showed `connected` regardless of whether it actually worked, since
this only checked key presence); ``connected`` otherwise. ``last_failure_at`` is that same real
recorded timestamp, not a fabricated one; ``p50_latency_ms`` stays ``null`` until the router
grows persistent latency telemetry.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.agents.llm_router import (
    get_provider_failure_status,
    get_provider_fallback_status,
    is_configured,
    load_routing_table,
)
from src.api.deps import get_current_user
from src.core.config import get_settings
from src.models.user import User
from src.orchestration.agent_config import KNOWN_PROVIDERS

# T105: how long a real complete() failure keeps a provider reported unreachable -- long enough
# that a transient blip doesn't stay flagged forever once the provider recovers (the next
# success clears it immediately anyway, see llm_router._ProviderFailureTracker.record_success),
# short enough that a genuinely broken provider (this session: HuggingFace credits depleted,
# OpenCode no payment method) shows unreachable for as long as no successful call proves
# otherwise.
PROVIDER_HEALTH_FAILURE_WINDOW = timedelta(minutes=10)

router = APIRouter(prefix="/api/v1/providers", tags=["providers"])


class ProviderOut(BaseModel):
    provider: str
    configured: bool
    models: list[str]


class ProviderHealthOut(BaseModel):
    provider: str
    availability: str  # "connected" | "unreachable"
    p50_latency_ms: int | None
    last_failure_at: str | None
    in_fallback: bool


def _models_by_provider() -> dict[str, list[str]]:
    out: dict[str, set[str]] = {}
    for chain in load_routing_table().values():
        for pm in chain:
            out.setdefault(pm.provider, set()).add(pm.model)
    return {k: sorted(v) for k, v in out.items()}


@router.get("", response_model=list[ProviderOut])
def list_providers(_user: User = Depends(get_current_user)) -> list[ProviderOut]:
    settings = get_settings()
    models = _models_by_provider()
    out: list[ProviderOut] = []
    for provider in sorted(KNOWN_PROVIDERS):
        configured = is_configured(provider, settings)
        if not configured:
            continue
        out.append(ProviderOut(provider=provider, configured=True, models=models.get(provider, [])))
    return out


@router.get("/health", response_model=list[ProviderHealthOut])
def provider_health(_user: User = Depends(get_current_user)) -> list[ProviderHealthOut]:
    settings = get_settings()
    failures = get_provider_failure_status()
    fallback_status = get_provider_fallback_status()
    now = datetime.now(UTC)
    out: list[ProviderHealthOut] = []
    for provider in sorted(KNOWN_PROVIDERS):
        configured = is_configured(provider, settings)
        last_failure = failures.get(provider)
        recently_failed = last_failure is not None and (now - last_failure) < (
            PROVIDER_HEALTH_FAILURE_WINDOW
        )
        out.append(
            ProviderHealthOut(
                provider=provider,
                availability="unreachable" if (not configured or recently_failed) else "connected",
                p50_latency_ms=None,
                last_failure_at=last_failure.isoformat() if last_failure else None,
                in_fallback=fallback_status.get(provider, False),
            )
        )
    return out
