"""Skill Admin API (REL-010 E10.6): the real toggle/grant surface for the
DB-015/DB-016-backed `SkillRegistry` (src/agents/tools/registry.py,
src/agents/tools/skill_registry_manager.py). Mirrors src/api/routers/audit.py's
`require_role`/`get_session`/Pydantic-response-model style.

UPDATE 2026-08-14 (REL-059): this module used to advertise itself as "API-025..032", a loose
range that was wrong on both ends -- API-025 (`/agents`, list all registered agents) and API-026
(`/agents/{agent_id}`, agent detail) are unrelated agent-roster rows in the ERDTM's "API
Traceability" sheet, not Skill rows. The real Skill-related IDs are API-027 (`GET /skills`),
API-028 (`POST /skills/install`, still No -- no dynamic package-install mechanism exists),
API-029 (`POST /skills/{skill_id}/enable`), API-030 (`POST /skills/{skill_id}/disable`), API-031
(`DELETE /skills/{skill_id}`, still No -- only the reversible disable toggle below exists;
`SkillRegistry.unregister()` has no route calling it), and API-032
(`GET /skills/{skill_id}/schema`) -- see each route's own docstring below. The `/agent-map`
routes and `GET /{name}` are not tracked under any API Traceability row at all; each says so
honestly in its own docstring below rather than borrowing a nearby ID.

Route order matters here: every literal-segment route (`/agent-map`, `/agent-map/{grant_id}`)
is registered BEFORE the dynamic `/{name}...` routes below it. FastAPI/Starlette matches routes
in registration order, so a `/{name}` route registered first would otherwise shadow
`GET /agent-map` (a request for it would incorrectly bind `name="agent-map"` to `get_skill`
instead of ever reaching `list_agent_skill_map`) -- a real bug found and fixed during this
epic's own implementation, not a hypothetical one.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents.tools.registry import SkillNotFoundError, get_skill_registry
from src.api.deps import require_role
from src.core.db import get_session
from src.core.security import ROLE_SYSTEM_ADMINISTRATOR
from src.models.skill import AgentSkillMap, Skill
from src.models.user import User

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])

_admin_only = require_role(ROLE_SYSTEM_ADMINISTRATOR, audit_denials=True)


class SkillSummary(BaseModel):
    name: str
    description: str | None
    version: str
    is_enabled: bool


def _get_skill_row_or_404(session: Session, name: str) -> Skill:
    row = session.scalar(select(Skill).where(Skill.name == name))
    if row is None:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    return row


def _to_summary(row: Skill) -> SkillSummary:
    return SkillSummary(
        name=row.name, description=row.description, version=row.version, is_enabled=row.is_enabled
    )


@router.get("", response_model=list[SkillSummary])
def list_skills() -> list[SkillSummary]:
    """API-027 (previously mislabeled "API-025" here, which is actually `/agents` -- list all
    registered agents; see the module docstring). Real catalog + real enable/disable state, both
    DB-backed (E10.6)."""
    with get_session() as session:
        rows = session.scalars(select(Skill).order_by(Skill.name))
        return [_to_summary(r) for r in rows]


class AgentSkillGrant(BaseModel):
    id: uuid.UUID
    agent_name: str
    skill_name: str
    granted_by_user_id: uuid.UUID
    granted_at: datetime


def _to_grant(row: AgentSkillMap, skill_name: str) -> AgentSkillGrant:
    return AgentSkillGrant(
        id=row.id,
        agent_name=row.agent_name,
        skill_name=skill_name,
        granted_by_user_id=row.granted_by_user_id,
        granted_at=row.granted_at,
    )


@router.get("/agent-map", response_model=list[AgentSkillGrant])
def list_agent_skill_map() -> list[AgentSkillGrant]:
    """Not tracked under its own API Traceability row (confirmed 2026-08-14: no row anywhere in
    the sheet mentions agent-skill grants) -- previously mislabeled "API-029" here, which is
    actually `POST /skills/{skill_id}/enable` (see enable_skill() below). Real DB-016 read."""
    with get_session() as session:
        rows = session.execute(
            select(AgentSkillMap, Skill.name).join(Skill, AgentSkillMap.skill_id == Skill.id)
        ).all()
        return [_to_grant(row, skill_name) for row, skill_name in rows]


class GrantSkillRequest(BaseModel):
    agent_name: str
    skill_name: str


@router.post("/agent-map", response_model=AgentSkillGrant, status_code=201)
def grant_skill_to_agent(
    body: GrantSkillRequest, user: User = Depends(_admin_only)
) -> AgentSkillGrant:
    """Not tracked under its own API Traceability row (confirmed 2026-08-14: no row anywhere in
    the sheet mentions agent-skill grants) -- previously mislabeled "API-030" here, which is
    actually `POST /skills/{skill_id}/disable` (see disable_skill() below)."""
    with get_session() as session:
        skill = _get_skill_row_or_404(session, body.skill_name)
        existing = session.scalar(
            select(AgentSkillMap).where(
                AgentSkillMap.agent_name == body.agent_name, AgentSkillMap.skill_id == skill.id
            )
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="This agent already has this skill granted")
        grant = AgentSkillMap(
            agent_name=body.agent_name,
            skill_id=skill.id,
            granted_by_user_id=user.id,
            granted_at=datetime.now(UTC),
        )
        session.add(grant)
        session.commit()
        session.refresh(grant)
        return _to_grant(grant, skill.name)


@router.delete("/agent-map/{grant_id}", status_code=204)
def revoke_skill_from_agent(grant_id: uuid.UUID, _user: User = Depends(_admin_only)) -> None:
    """Not tracked under its own API Traceability row (confirmed 2026-08-14: no row anywhere in
    the sheet mentions agent-skill grants) -- previously mislabeled "API-031" here, which is
    actually `DELETE /skills/{skill_id}` (still No in the ERDTM -- only the reversible disable
    toggle exists; `SkillRegistry.unregister()` has no route calling it)."""
    with get_session() as session:
        grant = session.get(AgentSkillMap, grant_id)
        if grant is None:
            raise HTTPException(status_code=404, detail="Grant not found")
        session.delete(grant)
        session.commit()


@router.get("/{name}", response_model=SkillSummary)
def get_skill(name: str) -> SkillSummary:
    """Not tracked under its own API Traceability row (confirmed 2026-08-14: no row anywhere in
    the sheet mentions a Skill-detail-by-name lookup) -- previously mislabeled "API-026" here,
    which is actually `/agents/{agent_id}` (agent detail); the ERDTM's own API-026 row notes this
    exact stale citation."""
    with get_session() as session:
        return _to_summary(_get_skill_row_or_404(session, name))


@router.get("/{name}/schema")
def get_skill_schema(name: str) -> dict[str, Any]:
    """API-032: real `pydantic_schema` JSONB -- `{}` for a skill that hasn't declared a real
    input schema yet (BaseSkill.input_schema defaults to None), never a fabricated one."""
    with get_session() as session:
        return _get_skill_row_or_404(session, name).pydantic_schema


@router.post("/{name}/enable", response_model=SkillSummary)
def enable_skill(name: str, _user: User = Depends(_admin_only)) -> SkillSummary:
    """API-029 (previously mislabeled "API-027" here, which is actually `GET /skills` -- see
    list_skills() above)."""
    try:
        get_skill_registry().enable(name, persist=True)
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    with get_session() as session:
        return _to_summary(_get_skill_row_or_404(session, name))


@router.post("/{name}/disable", response_model=SkillSummary)
def disable_skill(name: str, _user: User = Depends(_admin_only)) -> SkillSummary:
    """API-030 (previously mislabeled "API-028" here, which is actually `POST /skills/install`,
    still No -- see the module docstring)."""
    try:
        get_skill_registry().disable(name, persist=True)
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    with get_session() as session:
        return _to_summary(_get_skill_row_or_404(session, name))
