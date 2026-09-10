"""Per-agent provider/model resolution (spec T076, FR-104/106, research R11, clarify Q4/Q5).

Precedence when an LLM-backed node asks for a model:
  1. the global ``routing.yaml`` fallback chain for the task type (unchanged), and
  2. if the agent's ``AgentConfig`` is ``CUSTOM`` with a currently-valid ``(provider, model)``
     pair, that pair is prepended as the chain head.

``AUTO`` (the default) and a deterministic agent (``provider_model_mode IS NULL``) both return
``None`` here -- the router then behaves byte-for-byte as it did before this feature (SC-010).
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.agent_config import AgentConfig

logger = structlog.get_logger(__name__)

KNOWN_PROVIDERS = frozenset(
    {"openai", "anthropic", "deepseek", "gemini", "huggingface", "opencode", "ollama"}
)


def _config_row(session: Session, agent_slug: str) -> AgentConfig | None:
    return session.scalars(select(AgentConfig).where(AgentConfig.agent_slug == agent_slug)).first()


def known_models(provider: str) -> set[str]:
    """Models ``routing.yaml`` references for ``provider`` -- the offerable set (FR-105)."""
    from src.agents.llm_router import load_routing_table

    out: set[str] = set()
    for chain in load_routing_table().values():
        for pm in chain:
            if pm.provider == provider:
                out.add(pm.model)
    return out


def is_valid_pair(provider: str, model: str) -> bool:
    """Offerable only if the provider is known, currently configured (a real key present), and
    the model is one ``routing.yaml`` already uses for that provider (FR-105)."""
    if provider not in KNOWN_PROVIDERS or not model.strip():
        return False
    from src.agents.llm_router import is_configured
    from src.core.config import get_settings

    try:
        if not is_configured(provider, get_settings()):
            return False
    except Exception:  # noqa: BLE001 -- treat an unresolvable provider as not-offerable
        return False
    return model in known_models(provider)


def custom_pair(session: Session, agent_slug: str) -> tuple[str, str] | None:
    """The configured ``CUSTOM`` ``(provider, model)`` for this agent, or ``None`` when it is on
    ``AUTO`` / deterministic / not configured / the pair is no longer valid."""
    row = _config_row(session, agent_slug)
    if (
        row is None
        or row.provider_model_mode != "CUSTOM"
        or not row.custom_provider
        or not row.custom_model
    ):
        return None
    if not is_valid_pair(row.custom_provider, row.custom_model):
        logger.warning(
            "agent_custom_pair_invalid",
            agent_slug=agent_slug,
            provider=row.custom_provider,
            model=row.custom_model,
        )
        return None
    return row.custom_provider, row.custom_model


def resolve(agent_slug: str, task_type: str) -> tuple[str, str] | None:
    """Session-less entry point for the router. Returns the ``CUSTOM`` chain-head pair, or
    ``None`` for the unchanged ``AUTO`` path. ``task_type`` is accepted for the future
    per-task-override precedence level (research R11); it does not change the result today."""
    _ = task_type
    try:
        from src.core.db import get_session

        with get_session() as session:
            return custom_pair(session, agent_slug)
    except Exception as exc:  # noqa: BLE001 -- never let config resolution break a real LLM call
        logger.warning("agent_config_resolve_failed", agent_slug=agent_slug, error=str(exc))
        return None
