"""spec 002 US2: a per-agent `CUSTOM` provider/model override (`AgentConfig`) must actually
change which model a real agent invocation calls -- before this feature, the override was
fully built (DB, API, audit, UI) but no agent node ever passed `agent_name=` to `complete()`,
so it had zero effect. This proves the full round trip: a real `AgentConfig` row -> the real
`market_analyst_node`'s own `complete()` call (via `src/agents/nodes/market_analyst.py`,
`agent_name="market_analyst"`) -> the actual model requested changes to the CUSTOM pair.

Follows `tests/unit/test_llm_router_auto_unchanged.py`'s existing convention: the real
Postgres-backed AgentConfig row and the real `llm_router.complete()` resolution/prepend logic
are exercised for real; only the external LLM HTTP call itself (`litellm.completion`) is
mocked, avoiding a real network dependency for what this test actually needs to prove.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from src.agents import llm_router
from src.core.db import get_session
from src.models.agent_config import AgentConfig


def _fake_response() -> MagicMock:
    r = MagicMock()
    r.choices[0].message.content = '{"ok": true}'
    r.model = "fake"
    return r


def _set_market_analyst_custom(provider: str, model: str) -> None:
    with get_session() as session:
        row = AgentConfig(
            agent_slug="market_analyst",
            is_llm_backed=True,
            provider_model_mode="CUSTOM",
            custom_provider=provider,
            custom_model=model,
            updated_by="test",
            updated_at=datetime.now(UTC),
        )
        session.add(row)
        session.commit()


def _clear_market_analyst_config() -> None:
    with get_session() as session:
        session.query(AgentConfig).filter(AgentConfig.agent_slug == "market_analyst").delete()
        session.commit()


def test_custom_override_changes_the_actual_model_requested():
    # ollama needs no key and is deliberately always "configured" (per routing.yaml's own
    # comment) -- a safe, real, always-valid CUSTOM pair that differs from `research`'s AUTO
    # chain head (openai/gpt-4o), so a match proves the override, not a coincidence.
    _set_market_analyst_custom("ollama", "deepseek-r1:latest")
    try:
        with patch.object(llm_router.litellm, "completion", return_value=_fake_response()) as m:
            llm_router.complete(
                "research",
                [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
                agent_name="market_analyst",
            )
            requested_model = m.call_args_list[0].kwargs["model"]
        assert "deepseek-r1:latest" in requested_model
        assert "gpt-4o" not in requested_model
    finally:
        _clear_market_analyst_config()


def test_reverting_to_auto_restores_default_routing():
    _set_market_analyst_custom("ollama", "deepseek-r1:latest")
    try:
        with patch.object(llm_router.litellm, "completion", return_value=_fake_response()) as m:
            llm_router.complete(
                "research",
                [{"role": "user", "content": "x"}],
                agent_name="market_analyst",
            )
            custom_model = m.call_args_list[0].kwargs["model"]
    finally:
        _clear_market_analyst_config()

    # Reverted to AUTO (no AgentConfig row) -- the next call resolves the same as any
    # unconfigured agent (test_llm_router_auto_unchanged.py's own baseline).
    with patch.object(llm_router.litellm, "completion", return_value=_fake_response()) as m:
        llm_router.complete(
            "research",
            [{"role": "user", "content": "x"}],
            agent_name="market_analyst",
        )
        auto_model = m.call_args_list[0].kwargs["model"]

    assert auto_model != custom_model
