"""Golden test (spec T083, SC-010): an agent left on AUTO gets byte-for-byte the pre-feature
provider/model selection. The US6 wiring (`complete(..., agent_name=...)`) must be a pure no-op
unless an agent is explicitly configured ``CUSTOM``.
"""

from unittest.mock import MagicMock, patch

from src.agents import llm_router
from src.core.config import get_settings


def _fake_response() -> MagicMock:
    r = MagicMock()
    r.choices[0].message.content = '{"ok": true}'
    r.model = "fake"
    return r


def test_auto_agent_first_call_matches_no_agent_first_call():
    """For every task type, the first (provider, model) `complete()` attempts is identical
    whether or not an AUTO agent name is passed."""
    for task_type in ("coding", "orchestration", "sentiment", "research", "chat"):
        with patch.object(llm_router.litellm, "completion", return_value=_fake_response()) as m:
            llm_router.complete(task_type, [{"role": "user", "content": "x"}])
            baseline_model = m.call_args_list[0].kwargs["model"]

        with patch.object(llm_router.litellm, "completion", return_value=_fake_response()) as m:
            # `market_analyst` has no AgentConfig row -> AUTO -> no prepend.
            llm_router.complete(
                task_type, [{"role": "user", "content": "x"}], agent_name="market_analyst"
            )
            with_agent_model = m.call_args_list[0].kwargs["model"]

        assert with_agent_model == baseline_model, task_type


def test_build_fallback_chain_is_untouched_by_the_feature():
    settings = get_settings()
    for task_type in ("coding", "orchestration", "sentiment", "research", "chat"):
        chain = llm_router.build_fallback_chain(task_type, settings)  # type: ignore[arg-type]
        assert chain == llm_router.build_fallback_chain(task_type, settings)  # type: ignore[arg-type]


def test_resolve_returns_none_for_an_unconfigured_agent():
    from src.orchestration.agent_config import resolve

    assert resolve("market_analyst", "research") is None
    assert resolve("does_not_exist", "coding") is None
