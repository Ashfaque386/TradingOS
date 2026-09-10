"""LLM provider / model catalogue + health (spec T079, contracts/rest-api.md, FR-105/110).

``GET /api/v1/providers`` lists only providers that are actually configured (a real key present
via Vault or settings) with the models ``routing.yaml`` references for them. ``GET /health``
reports **real signals only** (constitution VI): a provider is ``connected`` when it is
configured, ``unreachable`` otherwise; latency / last-failure are ``null`` until the router
grows persistent telemetry -- never a fabricated number.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.agents.llm_router import is_configured, load_routing_table
from src.api.deps import get_current_user
from src.core.config import get_settings
from src.models.user import User
from src.orchestration.agent_config import KNOWN_PROVIDERS

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
    return [
        ProviderHealthOut(
            provider=provider,
            availability="connected" if is_configured(provider, settings) else "unreachable",
            p50_latency_ms=None,
            last_failure_at=None,
            in_fallback=False,
        )
        for provider in sorted(KNOWN_PROVIDERS)
    ]
