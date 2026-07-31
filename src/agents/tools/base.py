"""BaseSkill interface (Phase 2 Epic E2.1, per Phase_3_Low_Level_Design.md §9.1 / FR-12).

Agents are not hardcoded with static tools; they call skills loaded dynamically from the
SkillRegistry. A new capability is added by writing one BaseSkill subclass and registering it
-- no change to the LangGraph node or the agent's system prompt is required.
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseSkill(ABC):
    name: str
    description: str
    # REL-010 E10.6: defaulted so every pre-existing skill subclass keeps working unchanged.
    # `version` and `input_schema` are what src/agents/tools/skill_registry_manager.py persists
    # into the real `skills.version`/`skills.pydantic_schema` columns (DB-015) on boot -- a skill
    # that hasn't declared a real input schema yet gets `{}` there, not a fabricated one.
    version: str = "1.0.0"
    input_schema: dict[str, Any] | None = None

    @abstractmethod
    def execute(self, **kwargs: Any) -> Any: ...
