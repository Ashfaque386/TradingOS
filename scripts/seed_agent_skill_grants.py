"""spec 002 US8 cutover: seed a real `AgentSkillMap` grant for every (agent, skill) pair this
codebase's own real call sites actually exercise today, so enforcement (`SkillRegistry.execute`
now checking `agent_name` -- src/agents/tools/registry.py) doesn't silently break an agent that
was already, legitimately calling a skill before this feature existed.

Note on methodology: there is no per-skill-invocation audit log in this codebase (checked --
`AgentRun`/`AgentLog`/the event bus record agent- and task-level activity, never which specific
skill name was called), so "every (agent, skill) pair with at least one successful invocation in
the last 30 days" (the spec's original phrasing) is operationalised here as "every (agent,
skill) pair this feature's own code changes wired with `agent_name=`" -- the real, current,
exhaustively-grep-verified set of call sites (`grep -rn 'agent_name=' src/agents/nodes/*.py
src/api/routers/webhooks.py | grep -i skill_registry` finds all of them), which is exactly the
set that would otherwise regress on cutover. Idempotent: a grant that already exists is left
untouched, never re-created or altered (T042).

Run via `docker compose exec -T app python scripts/seed_agent_skill_grants.py` (one-time cutover,
same invocation pattern as the other `scripts/seed_*.py` fixtures).
"""

from datetime import UTC, datetime

from sqlalchemy import select

from src.agents.tools.registry import get_skill_registry
from src.core.db import get_session
from src.core.security import ROLE_SYSTEM_ADMINISTRATOR
from src.models.skill import AgentSkillMap, Skill
from src.models.user import User

# (agent_name, skill_name) -- the real, current call sites (spec 002 US8 / T038).
_REAL_GRANTS: list[tuple[str, str]] = [
    ("market_analyst", "fetch_global_indices"),
    ("market_analyst", "fetch_india_vix"),
    ("market_analyst", "fetch_nse_sector_data"),
    ("market_analyst", "query_macro_calendar"),
    ("python_code_generator", "search_code_templates"),
    ("python_code_generator", "format_python_code"),
    ("strategy_generator", "query_qdrant_strategy_memory"),
    ("notification_agent", "notify_omni_channel"),
]


def seed_agent_skill_grants() -> int:
    """Returns the number of grant rows actually inserted (0 on a re-run -- idempotent)."""
    get_skill_registry()  # ensures every ALL_SKILLS row exists in the DB catalog (DB-015) first

    inserted = 0
    with get_session() as session:
        # `granted_by_user_id` is a real, non-null FK to `users.id` -- this is a code-derived
        # cutover seed, not a real per-user grant decision, but it still needs a real actor.
        # Any real SystemAdministrator works equally well as the recorded actor; the first one
        # found is used, matching this script's own "run once" nature.
        seeder = session.scalar(select(User).where(User.role == ROLE_SYSTEM_ADMINISTRATOR))
        if seeder is None:
            raise RuntimeError(
                "no SystemAdministrator user exists yet -- run scripts/seed_admin_user.py first"
            )
        skill_ids = {
            name: skill_id for name, skill_id in session.execute(select(Skill.name, Skill.id)).all()
        }
        existing = set(
            session.execute(select(AgentSkillMap.agent_name, AgentSkillMap.skill_id)).all()
        )
        for agent_name, skill_name in _REAL_GRANTS:
            skill_id = skill_ids.get(skill_name)
            if skill_id is None:
                # A skill named here doesn't exist in the catalog -- a real, honest gap to
                # surface, not one to paper over by inventing a row for a skill that isn't real.
                print(f"WARNING: no Skill row for '{skill_name}' -- skipping grant to {agent_name}")
                continue
            if (agent_name, skill_id) in existing:
                continue
            session.add(
                AgentSkillMap(
                    agent_name=agent_name,
                    skill_id=skill_id,
                    granted_by_user_id=seeder.id,
                    granted_at=datetime.now(UTC),
                )
            )
            inserted += 1
        session.commit()
    return inserted


if __name__ == "__main__":
    count = seed_agent_skill_grants()
    print(f"Seeded {count} new AgentSkillMap grant(s) (idempotent -- re-run is always safe).")
