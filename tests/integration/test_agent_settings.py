"""Per-agent Settings API (spec T082 -- MANDATORY, brief section 81, quickstart Scenario 6,
SC-011/012/016).

- create a prompt version (inactive) -> activate -> a before/after audit entry is written;
- the router then serves the configured (provider, model) pair as the chain head for that agent;
- a CUSTOM pair with a model routing.yaml never uses -> 422;
- a deterministic agent's PUT /provider-model -> 422 (clarify Q5);
- any write by a PortfolioManager -> 403 with an audited denial.
"""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.agents import llm_router
from src.api.main import app
from src.core.db import get_session
from src.core.security import ROLE_PORTFOLIO_MANAGER, ROLE_SYSTEM_ADMINISTRATOR
from src.models.agent_config import AgentConfig, PromptVersion
from src.models.audit import AuditLog
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)

SLUG = "market_analyst_agent"
DET_SLUG = "python_validator_agent"


def _cleanup_config(slug: str) -> None:
    with get_session() as session:
        session.query(AgentConfig).filter(AgentConfig.agent_slug == slug).delete()
        session.query(PromptVersion).filter(
            PromptVersion.agent_slug == slug, PromptVersion.author.like("%@example%")
        ).delete()
        # restore the seeded v1 (system) as the active row
        rows = session.scalars(
            select(PromptVersion).where(
                PromptVersion.agent_slug == slug, PromptVersion.kind == "system"
            )
        ).all()
        for r in rows:
            r.is_active = r.version == 1
        session.commit()


def _fake_response() -> MagicMock:
    r = MagicMock()
    r.choices[0].message.content = '{"ok": true}'
    r.model = "fake"
    return r


def test_create_activate_audit_and_router_uses_the_configured_pair():
    sa_id, sa_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        # 1. create a new (inactive) system-prompt version
        created = client.post(
            f"/api/v1/agents/{SLUG}/config/prompts/system",
            json={"content": "You are the market analyst. Be terse.", "change_summary": "terser"},
            headers=auth_header(sa_token),
        )
        assert created.status_code == 201, created.text
        new_version = created.json()["version"]
        assert created.json()["is_active"] is False

        listed = client.get(
            f"/api/v1/agents/{SLUG}/config/prompts", headers=auth_header(sa_token)
        ).json()
        assert any(v["version"] == new_version and not v["is_active"] for v in listed)

        # 2. activate it -> a before/after audit entry
        act = client.post(
            f"/api/v1/agents/{SLUG}/config/prompts/system/{new_version}/activate",
            headers=auth_header(sa_token),
        )
        assert act.status_code == 200, act.text
        assert act.json()["is_active"] is True
        with get_session() as session:
            entries = session.scalars(
                select(AuditLog).where(AuditLog.action == "PROMPT_VERSION_ACTIVATED")
            ).all()
            assert any(
                (e.after_state or {}).get("active_version") == new_version
                and "active_version" in (e.before_state or {})
                for e in entries
            )

        # 3. set a CUSTOM provider/model pair (ollama is always configured; the model is real)
        put = client.put(
            f"/api/v1/agents/{SLUG}/config/provider-model",
            json={"mode": "CUSTOM", "provider": "ollama", "model": "deepseek-r1:latest"},
            headers=auth_header(sa_token),
        )
        assert put.status_code == 200, put.text
        cfg = client.get(f"/api/v1/agents/{SLUG}/config", headers=auth_header(sa_token)).json()
        assert cfg["provider_model"] == "ollama/deepseek-r1:latest"
        assert cfg["precedence"] == "custom (agent config)"

        # 4. the router now prepends that exact pair for this agent
        with patch.object(llm_router.litellm, "completion", return_value=_fake_response()) as m:
            llm_router.complete("research", [{"role": "user", "content": "x"}], agent_name=SLUG)
            assert m.call_args_list[0].kwargs["model"] == "ollama/deepseek-r1:latest"
    finally:
        cleanup_user(sa_id)
        _cleanup_config(SLUG)


def test_custom_pair_with_an_unknown_model_is_422():
    sa_id, sa_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        r = client.put(
            f"/api/v1/agents/{SLUG}/config/provider-model",
            json={"mode": "CUSTOM", "provider": "ollama", "model": "not-a-real-model:0"},
            headers=auth_header(sa_token),
        )
        assert r.status_code == 422
    finally:
        cleanup_user(sa_id)
        _cleanup_config(SLUG)


def test_deterministic_agent_cannot_configure_a_model():
    sa_id, sa_token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        cfg = client.get(f"/api/v1/agents/{DET_SLUG}/config", headers=auth_header(sa_token)).json()
        assert cfg["provider_model"] == "deterministic"
        r = client.put(
            f"/api/v1/agents/{DET_SLUG}/config/provider-model",
            json={"mode": "CUSTOM", "provider": "ollama", "model": "deepseek-r1:latest"},
            headers=auth_header(sa_token),
        )
        assert r.status_code == 422
    finally:
        cleanup_user(sa_id)


def test_portfolio_manager_write_is_forbidden_and_audited():
    pm_id, pm_token = create_authenticated_user(ROLE_PORTFOLIO_MANAGER)
    try:
        r = client.post(
            f"/api/v1/agents/{SLUG}/config/prompts/system",
            json={"content": "x", "change_summary": "y"},
            headers=auth_header(pm_token),
        )
        assert r.status_code == 403
        with get_session() as session:
            denials = session.scalars(
                select(AuditLog).where(AuditLog.action == "RBAC_DENIED")
            ).all()
            assert any(
                f"/api/v1/agents/{SLUG}/config/prompts/system"
                in (d.after_state or {}).get("path", "")
                for d in denials
            )
    finally:
        cleanup_user(pm_id)
