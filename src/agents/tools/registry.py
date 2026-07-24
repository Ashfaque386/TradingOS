"""SkillRegistry singleton (Phase 2 Epic E2.1).

Skills can be enabled/disabled at runtime (e.g. "ensure the Research Agent cannot access the
Execution Skill", per Phase_4_AI_Agent_Design.md §0) without an app restart -- toggling
`enable`/`disable` takes effect on the very next `execute()` call. This in-memory registry is
the Phase 2 implementation; it mirrors the DB-015 SKILLS / DB-016 AGENT_SKILL_MAP tables
already defined in Phase_11_Database_Design.md, which a later phase's admin API (API-0xx skill
toggle endpoints, Phase_10_API_Design.md) will persist to instead of holding only in memory.
"""

from functools import lru_cache
from typing import Any

from src.agents.tools.base import BaseSkill


class SkillNotFoundError(RuntimeError):
    pass


class SkillDisabledError(RuntimeError):
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

    def enable(self, name: str) -> None:
        self._require_registered(name)
        self._enabled[name] = True

    def disable(self, name: str) -> None:
        self._require_registered(name)
        self._enabled[name] = False

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

    def execute(self, name: str, **kwargs: Any) -> Any:
        return self.get(name).execute(**kwargs)

    def _require_registered(self, name: str) -> None:
        if name not in self._skills:
            raise SkillNotFoundError(f"no skill registered with name '{name}'")


@lru_cache
def get_skill_registry() -> SkillRegistry:
    registry = SkillRegistry()
    _bootstrap_default_skills(registry)
    return registry


def _bootstrap_default_skills(registry: SkillRegistry) -> None:
    from src.agents.tools.skills import ALL_SKILLS

    for skill in ALL_SKILLS:
        registry.register(skill)
