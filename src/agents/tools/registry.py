"""SkillRegistry singleton (Phase 2 Epic E2.1).

Skills can be enabled/disabled at runtime (e.g. "ensure the Research Agent cannot access the
Execution Skill", per Phase_4_AI_Agent_Design.md §0) without an app restart -- toggling
`enable`/`disable` takes effect on the very next `execute()` call.

REL-010 E10.6: the in-memory state here is no longer the only source of truth. On first access,
`get_skill_registry()` syncs against the real DB-015/DB-016 tables (`src/models/skill.py`) via
`skill_registry_manager.sync_registry_with_db` -- code (`ALL_SKILLS`) stays the *catalog* source
of truth (a skill only exists if it's really implemented), the DB becomes the *enable/disable
state* source of truth (so a toggle survives an app restart, per this epic's own exit
criterion). `enable`/`disable` gained an opt-in `persist: bool = False` kwarg that writes
through to that same DB row -- defaulted to False (not True) so `SkillRegistry` itself stays
DB-agnostic and safely unit-testable with an ad-hoc registry/skill that was never synced to the
DB (see tests/unit/test_skill_registry.py); `src/api/routers/skills.py`'s admin endpoints are
the one real call site that explicitly passes `persist=True`.
"""

from functools import lru_cache
from typing import Any

from src.agents.tools.base import BaseSkill


class SkillNotFoundError(RuntimeError):
    pass


class SkillDisabledError(RuntimeError):
    pass


class SkillNotGrantedError(RuntimeError):
    """spec 002 US8: `agent_name` was supplied to `execute()` but that agent has no
    `AgentSkillMap` grant for this skill -- a per-agent restriction, additive to (never a
    substitute for) the global enable/disable switch above."""

    pass


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, BaseSkill] = {}
        self._enabled: dict[str, bool] = {}

    def register(self, skill: BaseSkill, *, enabled: bool = True) -> None:
        self._skills[skill.name] = skill
        self._enabled[skill.name] = enabled

    def unregister(self, name: str) -> None:
        self._skills.pop(name, None)
        self._enabled.pop(name, None)

    def enable(self, name: str, *, persist: bool = False) -> None:
        self._require_registered(name)
        self._enabled[name] = True
        if persist:
            self._persist_enabled_state(name, True)

    def disable(self, name: str, *, persist: bool = False) -> None:
        self._require_registered(name)
        self._enabled[name] = False
        if persist:
            self._persist_enabled_state(name, False)

    def is_enabled(self, name: str) -> bool:
        self._require_registered(name)
        return self._enabled[name]

    def list_skills(self) -> list[str]:
        return sorted(self._skills)

    def get(self, name: str) -> BaseSkill:
        self._require_registered(name)
        if not self._enabled[name]:
            raise SkillDisabledError(f"skill '{name}' is disabled")
        return self._skills[name]

    def execute(self, name: str, *, agent_name: str | None = None, **kwargs: Any) -> Any:
        """spec 002 US8: when `agent_name` is supplied, this agent must hold a real
        `AgentSkillMap` grant for `name`, in addition to the skill being globally enabled
        (`get()` above). `agent_name=None` (the default -- every call site not yet updated to
        pass it) preserves today's behaviour exactly: no per-agent check, matching the
        already-existing global enable/disable gate only."""
        skill = self.get(name)
        if agent_name is not None and not self._has_grant(agent_name, name):
            raise SkillNotGrantedError(f"agent '{agent_name}' is not granted skill '{name}'")
        return skill.execute(**kwargs)

    def _has_grant(self, agent_name: str, skill_name: str) -> bool:
        from sqlalchemy import select

        from src.core.db import get_session
        from src.models.skill import AgentSkillMap
        from src.models.skill import Skill as SkillModel

        with get_session() as session:
            skill_row = session.scalar(select(SkillModel).where(SkillModel.name == skill_name))
            if skill_row is None:
                # No DB-015 catalog row for this skill (e.g. a test-only in-memory skill never
                # synced to the DB) -- nothing to grant against, so there is nothing to deny
                # either; the global enabled/disabled check above remains the only real gate.
                return True
            grant = session.scalar(
                select(AgentSkillMap).where(
                    AgentSkillMap.agent_name == agent_name,
                    AgentSkillMap.skill_id == skill_row.id,
                )
            )
            return grant is not None

    def _require_registered(self, name: str) -> None:
        if name not in self._skills:
            raise SkillNotFoundError(f"no skill registered with name '{name}'")

    def _persist_enabled_state(self, name: str, is_enabled: bool) -> None:
        # Lazy import (same reason _bootstrap_default_skills below imports skills.py lazily):
        # skill_registry_manager.py imports SkillRegistry from this module for its type hints,
        # so importing it at module scope here would be circular.
        from src.agents.tools.skill_registry_manager import persist_skill_enabled_state

        persist_skill_enabled_state(name, is_enabled)


@lru_cache
def get_skill_registry() -> SkillRegistry:
    registry = SkillRegistry()
    _bootstrap_default_skills(registry)
    _sync_with_db(registry)
    return registry


def _bootstrap_default_skills(registry: SkillRegistry) -> None:
    from src.agents.tools.skills import ALL_SKILLS

    for skill in ALL_SKILLS:
        registry.register(skill, enabled=True)


def _sync_with_db(registry: SkillRegistry) -> None:
    # REL-010 E10.6: a DB outage at boot must never break skill execution -- degrades to the
    # code-default `enabled=True` for everything (set by _bootstrap_default_skills above) rather
    # than raising out of get_skill_registry(), matching the fail-open-on-infra-outage
    # convention already used throughout src/agents/nodes/.
    try:
        from src.agents.tools.skill_registry_manager import sync_registry_with_db

        sync_registry_with_db(registry)
    except Exception:  # noqa: BLE001 - see comment above
        pass
