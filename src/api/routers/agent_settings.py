"""Per-agent Settings API (spec T078, contracts/rest-api.md, FR-100..110, clarify Q4/Q5).

Prefix ``/api/v1/agents/{agent_slug}/config`` where ``agent_slug`` is the prompt-registry slug
(e.g. ``market_analyst_agent``, ``ceo_planner``). Prompt version history / activate / rollback,
provider-model mode (``AUTO`` = today's routing, unchanged), and a no-side-effect test panel.
Every write is ``SystemAdministrator``-only and audited.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents import prompt_registry
from src.agents.llm_router import NoProviderAvailableError, complete
from src.api.deps import get_current_user, require_role
from src.core.audit import write_audit_entry
from src.core.db import get_session
from src.core.security import ROLE_SYSTEM_ADMINISTRATOR
from src.models.agent_config import AgentConfig, PromptVersion
from src.models.user import User
from src.orchestration.agent_config import KNOWN_PROVIDERS, is_valid_pair

router = APIRouter(prefix="/api/v1/agents/{agent_slug}/config", tags=["agent-settings"])

_can_manage = require_role(ROLE_SYSTEM_ADMINISTRATOR, audit_denials=True)


def _is_llm_backed(agent_slug: str, row: AgentConfig | None) -> bool:
    if row is not None:
        return row.is_llm_backed
    from src.orchestration.capability_registry import AGENT_META

    for key in (agent_slug, agent_slug.removesuffix("_agent")):
        if key in AGENT_META:
            return AGENT_META[key].is_llm_backed
    return True


class AgentConfigOut(BaseModel):
    agent_slug: str
    is_llm_backed: bool
    provider_model_mode: str | None
    provider_model: str  # "deterministic" | "AUTO" | "<provider>/<model>"
    precedence: str  # "deterministic" | "auto (routing.yaml)" | "custom (agent config)"
    active_prompts: dict[str, int | None]
    updated_by: str | None


class PromptVersionOut(BaseModel):
    kind: str
    version: int
    author: str
    change_summary: str
    is_active: bool
    created_at: str


class PromptContentOut(BaseModel):
    kind: str
    version: int
    content: str
    is_active: bool


class CreatePromptRequest(BaseModel):
    content: str = Field(min_length=1)
    change_summary: str = Field(min_length=1)


class ProviderModelRequest(BaseModel):
    mode: str  # "AUTO" | "CUSTOM"
    provider: str | None = None
    model: str | None = None


class TestRequest(BaseModel):
    kind: str = "system"
    version: int | None = None
    provider: str | None = None
    model: str | None = None


class TestResult(BaseModel):
    provider: str | None
    model: str | None
    latency_ms: int
    structured_output_valid: bool
    tool_compatible: bool
    errors: list[str]


def _config(session: Session, agent_slug: str) -> AgentConfig | None:
    row: AgentConfig | None = session.scalars(
        select(AgentConfig).where(AgentConfig.agent_slug == agent_slug)
    ).first()
    return row


def _versions(session: Session, agent_slug: str) -> list[PromptVersion]:
    base = agent_slug
    return list(
        session.scalars(
            select(PromptVersion)
            .where(PromptVersion.agent_slug == base)
            .order_by(PromptVersion.kind, PromptVersion.version)
        ).all()
    )


@router.get("", response_model=AgentConfigOut)
def get_config(agent_slug: str, _user: User = Depends(get_current_user)) -> AgentConfigOut:
    with get_session() as session:
        row = _config(session, agent_slug)
        llm = _is_llm_backed(agent_slug, row)
        versions = _versions(session, agent_slug)
        active = {
            k: next((v.version for v in versions if v.kind == k and v.is_active), None)
            for k in {v.kind for v in versions} or {"system"}
        }
        if not llm:
            return AgentConfigOut(
                agent_slug=agent_slug,
                is_llm_backed=False,
                provider_model_mode=None,
                provider_model="deterministic",
                precedence="deterministic",
                active_prompts=active,
                updated_by=row.updated_by if row else None,
            )
        mode = (row.provider_model_mode if row else None) or "AUTO"
        if mode == "CUSTOM" and row and row.custom_provider and row.custom_model:
            return AgentConfigOut(
                agent_slug=agent_slug,
                is_llm_backed=True,
                provider_model_mode="CUSTOM",
                provider_model=f"{row.custom_provider}/{row.custom_model}",
                precedence="custom (agent config)",
                active_prompts=active,
                updated_by=row.updated_by,
            )
        return AgentConfigOut(
            agent_slug=agent_slug,
            is_llm_backed=True,
            provider_model_mode="AUTO",
            provider_model="AUTO",
            precedence="auto (routing.yaml)",
            active_prompts=active,
            updated_by=row.updated_by if row else None,
        )


@router.get("/prompts", response_model=list[PromptVersionOut])
def list_prompt_versions(
    agent_slug: str, _user: User = Depends(get_current_user)
) -> list[PromptVersionOut]:
    with get_session() as session:
        return [
            PromptVersionOut(
                kind=v.kind,
                version=v.version,
                author=v.author,
                change_summary=v.change_summary,
                is_active=v.is_active,
                created_at=v.created_at.isoformat() if v.created_at else "",
            )
            for v in _versions(session, agent_slug)
        ]


@router.get("/prompts/{kind}/{version}", response_model=PromptContentOut)
def get_prompt_version(
    agent_slug: str, kind: str, version: int, _user: User = Depends(get_current_user)
) -> PromptContentOut:
    with get_session() as session:
        row = session.scalars(
            select(PromptVersion).where(
                PromptVersion.agent_slug == agent_slug,
                PromptVersion.kind == kind,
                PromptVersion.version == version,
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="No such prompt version")
        return PromptContentOut(
            kind=row.kind, version=row.version, content=row.content, is_active=row.is_active
        )


@router.post("/prompts/{kind}", response_model=PromptVersionOut, status_code=201)
def create_prompt_version(
    agent_slug: str,
    kind: str,
    body: CreatePromptRequest,
    user: User = Depends(_can_manage),
) -> PromptVersionOut:
    from datetime import UTC, datetime

    with get_session() as session:
        existing = session.scalars(
            select(PromptVersion.version).where(
                PromptVersion.agent_slug == agent_slug, PromptVersion.kind == kind
            )
        ).all()
        next_version = (max(existing) + 1) if existing else 1
        row = PromptVersion(
            agent_slug=agent_slug,
            kind=kind,
            version=next_version,
            content=body.content,
            author=user.email,
            change_summary=body.change_summary,
            is_active=False,
            created_at=datetime.now(UTC),
        )
        session.add(row)
        session.flush()
        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=user.email,
            action="PROMPT_VERSION_CREATED",
            entity_type="PromptVersion",
            entity_id=row.id,
            after_state={"agent_slug": agent_slug, "kind": kind, "version": next_version},
        )
        session.commit()
        return PromptVersionOut(
            kind=kind,
            version=next_version,
            author=user.email,
            change_summary=body.change_summary,
            is_active=False,
            created_at=row.created_at.isoformat(),
        )


@router.post("/prompts/{kind}/{version}/activate", response_model=PromptVersionOut)
def activate_prompt_version(
    agent_slug: str, kind: str, version: int, user: User = Depends(_can_manage)
) -> PromptVersionOut:
    try:
        prompt_registry.activate(agent_slug, kind, version, actor=user.email)
    except prompt_registry.PromptNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return _one(agent_slug, kind, version)


@router.post("/prompts/{kind}/{version}/rollback", response_model=PromptVersionOut)
def rollback_prompt_version(
    agent_slug: str, kind: str, version: int, user: User = Depends(_can_manage)
) -> PromptVersionOut:
    # `version` is the path anchor for the alias; rollback targets the previous version.
    _ = version
    try:
        target = prompt_registry.rollback(agent_slug, kind, actor=user.email)
    except prompt_registry.PromptNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return _one(agent_slug, kind, target)


def _one(agent_slug: str, kind: str, version: int) -> PromptVersionOut:
    with get_session() as session:
        base, resolved = prompt_registry.resolve_slug(agent_slug, kind)
        row = session.scalars(
            select(PromptVersion).where(
                PromptVersion.agent_slug == base,
                PromptVersion.kind == resolved,
                PromptVersion.version == version,
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="No such prompt version")
        return PromptVersionOut(
            kind=row.kind,
            version=row.version,
            author=row.author,
            change_summary=row.change_summary,
            is_active=row.is_active,
            created_at=row.created_at.isoformat() if row.created_at else "",
        )


@router.put("/provider-model", response_model=AgentConfigOut)
def set_provider_model(
    agent_slug: str, body: ProviderModelRequest, user: User = Depends(_can_manage)
) -> AgentConfigOut:
    from datetime import UTC, datetime

    if body.mode not in ("AUTO", "CUSTOM"):
        raise HTTPException(status_code=422, detail="mode must be 'AUTO' or 'CUSTOM'")
    with get_session() as session:
        row = _config(session, agent_slug)
        if not _is_llm_backed(agent_slug, row):
            raise HTTPException(
                status_code=422,
                detail="This agent is deterministic — it has no model to configure (clarify Q5).",
            )
        if body.mode == "CUSTOM":
            if not body.provider or not body.model:
                raise HTTPException(status_code=422, detail="CUSTOM requires provider and model")
            if body.provider not in KNOWN_PROVIDERS or not is_valid_pair(body.provider, body.model):
                raise HTTPException(
                    status_code=422,
                    detail=f"'{body.provider}/{body.model}' is not a configured, valid pair",
                )
        before = (
            None
            if row is None
            else {
                "mode": row.provider_model_mode,
                "provider": row.custom_provider,
                "model": row.custom_model,
            }
        )
        if row is None:
            row = AgentConfig(
                agent_slug=agent_slug,
                is_llm_backed=True,
                updated_at=datetime.now(UTC),
            )
            session.add(row)
        row.provider_model_mode = body.mode
        row.custom_provider = body.provider if body.mode == "CUSTOM" else None
        row.custom_model = body.model if body.mode == "CUSTOM" else None
        row.updated_by = user.email
        row.updated_at = datetime.now(UTC)
        session.flush()
        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=user.email,
            action="AGENT_PROVIDER_MODEL_CHANGED",
            entity_type="AgentConfig",
            entity_id=row.id,
            before_state=before,
            after_state={
                "mode": body.mode,
                "provider": row.custom_provider,
                "model": row.custom_model,
            },
        )
        session.commit()
    return get_config(agent_slug, user)


@router.post("/test", response_model=TestResult)
def test_agent_config(
    agent_slug: str, body: TestRequest, _user: User = Depends(_can_manage)
) -> TestResult:
    """Runs the selected prompt + (provider, model) against the real router once, without
    activating anything (FR-108). Uses a fixed structured-output probe."""
    errors: list[str] = []
    base, resolved = prompt_registry.resolve_slug(agent_slug, body.kind)
    try:
        system = prompt_registry.get_active_prompt(agent_slug, body.kind)
    except prompt_registry.PromptNotFoundError as exc:
        system = "You are a test agent."
        errors.append(f"prompt lookup failed: {exc}")

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": 'Reply with exactly this JSON: {"ok": true}'},
    ]
    _ = (base, resolved)
    provider = body.provider
    model = body.model
    started = time.perf_counter()
    structured_valid = False
    try:
        if provider and model:
            if not is_valid_pair(provider, model):
                raise ValueError(f"'{provider}/{model}' is not a configured, valid pair")
            import litellm

            from src.agents.llm_router import ProviderModel, _litellm_kwargs
            from src.core.config import get_settings

            response = litellm.completion(
                messages=messages,
                **_litellm_kwargs(ProviderModel(provider, model), get_settings()),
                timeout=get_settings().llm_call_timeout_seconds,
            )
        else:
            response = complete("orchestration", messages)
            model = getattr(response, "model", model)
        content = response.choices[0].message.content or ""
        structured_valid = '"ok"' in content and "true" in content.lower()
    except NoProviderAvailableError as exc:
        errors.append(str(exc))
    except Exception as exc:  # noqa: BLE001 -- the test panel reports failures, never raises
        errors.append(f"{type(exc).__name__}: {exc}")
    latency_ms = int((time.perf_counter() - started) * 1000)

    return TestResult(
        provider=provider,
        model=model,
        latency_ms=latency_ms,
        structured_output_valid=structured_valid,
        tool_compatible=not errors,
        errors=errors,
    )
