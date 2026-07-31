"""Skill Registry Manager Agent (AGT-023, REL-010 E10.6).

This module IS the "agent" -- there is no LangGraph node for it (matching the precedent already
set by AGT-021 Audit Agent, which is also implemented as plain service functions rather than a
graph node, since neither does any LLM-driven reasoning). Its job is purely mechanical: keep the
real `skills`/`agent_skill_map` DB tables (DB-015/DB-016, `src/models/skill.py`) in sync with the
in-memory `SkillRegistry` (`src/agents/tools/registry.py`), so a skill's enable/disable state
survives an app restart -- this is what closes REL-010's exit criterion #3.

Design: code (`ALL_SKILLS` in skills.py) is always the *catalog* source of truth -- a skill only
exists here if it's really implemented. The DB is the *enable/disable state* source of truth.
`sync_registry_with_db` is one-directional on the catalog (insert-if-missing, NEVER deletes a
`Skill` row even if the code-level skill later disappears, so a stale row is a real, visible,
investigatable fact rather than silently vanishing) and one-directional the other way for state
(DB `is_enabled` always wins over the code-registered default once a DB row exists).

Correction found during REL-010 implementation: earlier planning research (this session)
believed `skills`/`agent_skill_map` had no migration at all. A real `alembic upgrade head` run
proved otherwise -- both tables were already created by the very first migration
(`6cd568130517_initial_schema.py`), schema-identical to `src/models/skill.py`. No new migration
was needed; the real gap was only ever the missing read/write wiring this module provides.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from src.core.db import get_session
from src.models.skill import Skill

if TYPE_CHECKING:
    from src.agents.tools.registry import SkillRegistry


def sync_registry_with_db(registry: SkillRegistry) -> None:
    """Called once per process from `get_skill_registry()` after the code-level bootstrap.
    Must never raise on a genuine DB outage -- the caller already wraps this in a broad
    try/except for exactly that reason, so failures here are allowed to propagate."""
    from src.agents.tools.skills import ALL_SKILLS

    with get_session() as session:
        existing_names = set(session.scalars(select(Skill.name)))
        for skill in ALL_SKILLS:
            if skill.name not in existing_names:
                session.add(
                    Skill(
                        name=skill.name,
                        description=skill.description,
                        pydantic_schema=skill.input_schema or {},
                        version=skill.version,
                        is_enabled=True,
                    )
                )
        session.commit()

        # DB is authoritative for enable/disable state once a row exists -- apply it onto the
        # in-memory registry (persist=False: this is a read-back, not an admin action, and must
        # not re-trigger a write to the very row it just read).
        rows = session.execute(select(Skill.name, Skill.is_enabled)).all()
        for name, is_enabled in rows:
            if name not in registry.list_skills():
                continue  # a DB row with no matching code-level skill -- real, visible, unactioned
            if is_enabled:
                registry.enable(name, persist=False)
            else:
                registry.disable(name, persist=False)


def persist_skill_enabled_state(name: str, is_enabled: bool) -> None:
    """Write-through target for `SkillRegistry.enable`/`.disable` -- a real DB row must exist
    (created by `sync_registry_with_db` on the previous boot, or this boot if this is the first
    admin action after a fresh deploy) or this is a real bug, not silently swallowed."""
    with get_session() as session:
        skill = session.scalar(select(Skill).where(Skill.name == name))
        if skill is None:
            raise RuntimeError(
                f"skill '{name}' has no DB row yet -- sync_registry_with_db() should have "
                "created one at boot; this indicates get_skill_registry() was never called "
                "before this write, which should not happen in the real running app"
            )
        skill.is_enabled = is_enabled
        session.commit()
