"""REL-010 E10.6 exit criterion #3: "the Skill Registry survives a restart with its
enable/disable state intact (proving real DB persistence, not just in-memory)."

Real process restarts aren't reproducible inside one pytest run, so this test simulates one the
way `get_skill_registry()`'s own `@lru_cache` allows: clearing the cache forces the next call to
rebuild the in-memory `SkillRegistry` from scratch, exactly like a fresh `docker compose restart
app` would -- the only thing that can survive that rebuild is whatever is genuinely in Postgres,
not anything held in a Python variable.
"""

from sqlalchemy import select

from src.agents.tools.registry import get_skill_registry
from src.core.db import get_session
from src.models.skill import Skill

_TARGET_SKILL = "fetch_portfolio_status"  # real, already-implemented skill, safe to toggle


def _real_db_is_enabled(name: str) -> bool:
    with get_session() as session:
        row = session.scalar(select(Skill).where(Skill.name == name))
        assert row is not None, f"sync_registry_with_db should have created a row for {name!r}"
        return row.is_enabled


def test_disabling_a_skill_survives_a_simulated_restart():
    get_skill_registry()  # ensure the real DB row exists (sync_registry_with_db runs on boot)
    assert _real_db_is_enabled(_TARGET_SKILL) is True

    try:
        get_skill_registry().disable(_TARGET_SKILL, persist=True)
        assert _real_db_is_enabled(_TARGET_SKILL) is False

        get_skill_registry.cache_clear()  # simulates `docker compose restart app`
        rebuilt_registry = get_skill_registry()

        assert rebuilt_registry.is_enabled(_TARGET_SKILL) is False
        assert _real_db_is_enabled(_TARGET_SKILL) is False
    finally:
        get_skill_registry().enable(_TARGET_SKILL, persist=True)
        get_skill_registry.cache_clear()
        get_skill_registry()  # leave a clean, re-synced singleton for any later test in this run
