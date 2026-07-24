from typing import Any

import pytest

from src.agents.tools.base import BaseSkill
from src.agents.tools.registry import SkillDisabledError, SkillNotFoundError, SkillRegistry


class _EchoSkill(BaseSkill):
    name = "echo"
    description = "Returns whatever it's given."

    def execute(self, **kwargs: Any) -> Any:
        return kwargs


def test_register_and_execute():
    registry = SkillRegistry()
    registry.register(_EchoSkill())
    assert registry.execute("echo", value=42) == {"value": 42}


def test_unregistered_skill_raises():
    registry = SkillRegistry()
    with pytest.raises(SkillNotFoundError):
        registry.get("nonexistent")


def test_disable_blocks_execution():
    registry = SkillRegistry()
    registry.register(_EchoSkill())
    registry.disable("echo")
    assert registry.is_enabled("echo") is False
    with pytest.raises(SkillDisabledError):
        registry.execute("echo", value=1)


def test_enable_restores_execution():
    registry = SkillRegistry()
    registry.register(_EchoSkill(), enabled=False)
    registry.enable("echo")
    assert registry.execute("echo") == {}


def test_list_skills_is_sorted():
    registry = SkillRegistry()
    registry.register(_EchoSkill())

    class _AnotherSkill(BaseSkill):
        name = "aardvark"
        description = "test"

        def execute(self, **kwargs: Any) -> Any:
            return None

    registry.register(_AnotherSkill())
    assert registry.list_skills() == ["aardvark", "echo"]


def test_unregister_removes_skill():
    registry = SkillRegistry()
    registry.register(_EchoSkill())
    registry.unregister("echo")
    with pytest.raises(SkillNotFoundError):
        registry.get("echo")


def test_get_skill_registry_bootstraps_all_default_skills():
    from src.agents.tools.registry import get_skill_registry

    registry = get_skill_registry()
    expected = {
        "query_qdrant_strategy_memory",
        "search_code_templates",
        "format_python_code",
        "run_linter",
        "static_safety_check",
        "fetch_portfolio_status",
        "fetch_global_indices",
        "fetch_india_vix",
        "fetch_nse_sector_data",
        "query_macro_calendar",
        "notify_omni_channel",
    }
    assert expected.issubset(set(registry.list_skills()))
