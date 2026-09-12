"""spec 002 US8: `SkillRegistry.execute(name, agent_name=...)` genuinely enforces a real
`AgentSkillMap` grant -- granting a skill to one agent and not another actually changes who can
invoke it, closing the "recorded but inert" gap the original audit found (the grant table and
its CRUD API already existed; nothing ever read them at call time).

Uses the real DB-synced `get_skill_registry()` singleton and a real, harmless catalog skill
(`format_python_code`, a pure formatting call with no external side effects) rather than an
ad-hoc in-memory registry, so this exercises the exact code path a real agent node hits.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from src.agents.tools.registry import SkillNotGrantedError, get_skill_registry
from src.core.db import get_session
from src.core.security import ROLE_SYSTEM_ADMINISTRATOR
from src.models.skill import AgentSkillMap, Skill
from src.models.user import User

_GRANTED_AGENT = "test_agent_with_grant"
_UNGRANTED_AGENT = "test_agent_without_grant"


def _seed_grant() -> uuid.UUID:
    get_skill_registry()  # ensure the real Skill catalog row exists
    with get_session() as session:
        skill = session.scalar(select(Skill).where(Skill.name == "format_python_code"))
        assert skill is not None, "format_python_code must already be a real catalog skill"
        seeder = session.scalar(select(User).where(User.role == ROLE_SYSTEM_ADMINISTRATOR))
        assert seeder is not None, "run scripts/seed_admin_user.py first"
        grant = AgentSkillMap(
            agent_name=_GRANTED_AGENT,
            skill_id=skill.id,
            granted_by_user_id=seeder.id,
            granted_at=datetime.now(UTC),
        )
        session.add(grant)
        session.commit()
        return grant.id


def _cleanup_grant(grant_id: uuid.UUID) -> None:
    with get_session() as session:
        session.query(AgentSkillMap).filter(AgentSkillMap.id == grant_id).delete()
        session.commit()


def test_a_granted_agent_can_invoke_the_skill():
    grant_id = _seed_grant()
    try:
        result = get_skill_registry().execute(
            "format_python_code", agent_name=_GRANTED_AGENT, code="x=1"
        )
        assert result  # black-formatted output, non-empty
    finally:
        _cleanup_grant(grant_id)


def test_an_ungranted_agent_is_refused_with_skill_not_granted_error_not_an_uncaught_exception():
    grant_id = _seed_grant()
    try:
        with pytest.raises(SkillNotGrantedError):
            get_skill_registry().execute(
                "format_python_code", agent_name=_UNGRANTED_AGENT, code="x=1"
            )
    finally:
        _cleanup_grant(grant_id)


def test_no_agent_name_preserves_todays_unchanged_behaviour():
    # A call site not yet updated to pass agent_name= (or one that deliberately never scopes a
    # skill per-agent) must see zero behaviour change -- the global enable/disable gate only.
    result = get_skill_registry().execute("format_python_code", code="x=1")
    assert result


def test_seed_agent_skill_grants_is_idempotent_and_never_alters_a_pre_existing_grant():
    """spec 002 US8 T042: re-running the cutover seed script never removes or alters a grant
    that already exists (including one a real SA manually created via the UI, not the seed
    script itself)."""
    from scripts.seed_agent_skill_grants import seed_agent_skill_grants

    manual_grant_id = _seed_grant()  # simulates a pre-existing, real (non-seed-script) grant
    try:
        with get_session() as session:
            before = session.get(AgentSkillMap, manual_grant_id)
            assert before is not None
            before_granted_at = before.granted_at

        first_run_count = seed_agent_skill_grants()
        second_run_count = seed_agent_skill_grants()

        # The second run finds every pair the first run already inserted -- nothing new to add.
        assert second_run_count == 0

        with get_session() as session:
            after = session.get(AgentSkillMap, manual_grant_id)
            assert after is not None, "the pre-existing manual grant must not be deleted"
            assert after.granted_at == before_granted_at, "must not be altered"

        # Clean up whatever the seed script itself inserted, so this test doesn't leave behind
        # permanent grants for the real agents it names.
        with get_session() as session:
            session.query(AgentSkillMap).filter(
                AgentSkillMap.agent_name.in_(
                    [
                        "market_analyst",
                        "python_code_generator",
                        "strategy_generator",
                        "notification_agent",
                    ]
                )
            ).delete(synchronize_session=False)
            session.commit()
        assert first_run_count >= 0  # sanity: ran without error
    finally:
        _cleanup_grant(manual_grant_id)
