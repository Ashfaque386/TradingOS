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

    @abstractmethod
    def execute(self, **kwargs: Any) -> Any: ...
