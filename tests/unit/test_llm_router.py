from unittest.mock import patch

import pytest

from src.agents.llm_router import (
    NoProviderAvailableError,
    ProviderModel,
    build_fallback_chain,
    complete,
    is_configured,
    load_routing_table,
)
from src.core.config import Settings


def _settings(**overrides) -> Settings:
    """`vault_addr=None` by default: `is_configured`/`_litellm_kwargs` now check Vault first
    (REL-002 E2.2), so without this these "unit" tests would silently depend on whatever this
    dev machine's real Vault happens to have stored for LLM provider keys — the exact same
    live-Vault test-isolation risk already caught and fixed for test_broker_factory.py."""
    overrides.setdefault("vault_addr", None)
    return Settings(_env_file=None, **overrides)


def test_ollama_is_always_configured():
    assert is_configured("ollama", _settings()) is True


def test_cloud_provider_unconfigured_without_key():
    assert is_configured("openai", _settings()) is False
    assert is_configured("huggingface", _settings()) is False


def test_cloud_provider_configured_with_key():
    assert is_configured("openai", _settings(openai_api_key="sk-test")) is True
    assert is_configured("huggingface", _settings(hf_token="hf_test")) is True


def test_build_fallback_chain_filters_unconfigured_providers():
    settings = _settings(anthropic_api_key="sk-ant-test")
    chain = build_fallback_chain("coding", settings)
    providers = [pm.provider for pm in chain]
    assert providers == ["anthropic", "ollama"]  # deepseek/opencode skipped, ollama always last


def test_build_fallback_chain_with_no_cloud_keys_still_has_ollama():
    chain = build_fallback_chain("orchestration", _settings())
    assert chain == [ProviderModel("ollama", "deepseek-r1:latest")]


def test_complete_falls_back_to_next_provider_on_failure():
    settings = _settings(anthropic_api_key="sk-ant-test")
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"].startswith("anthropic/"):
            raise RuntimeError("simulated anthropic outage")
        return {"choices": [{"message": {"content": "ok"}}]}

    with (
        patch("src.agents.llm_router.get_settings", return_value=settings),
        patch("src.agents.llm_router.litellm.completion", side_effect=fake_completion),
    ):
        result = complete("coding", messages=[{"role": "user", "content": "hi"}])

    assert calls == ["anthropic/claude-3-7-sonnet-20250219", "ollama/deepseek-r1:latest"]
    assert result == {"choices": [{"message": {"content": "ok"}}]}


def test_complete_raises_when_every_provider_fails():
    settings = _settings()

    with (
        patch("src.agents.llm_router.get_settings", return_value=settings),
        patch("src.agents.llm_router.litellm.completion", side_effect=RuntimeError("down")),
        pytest.raises(NoProviderAvailableError),
    ):
        complete("orchestration", messages=[{"role": "user", "content": "hi"}])


def test_complete_uses_configured_provider_first_try():
    settings = _settings(openai_api_key="sk-test")

    with (
        patch("src.agents.llm_router.get_settings", return_value=settings),
        patch(
            "src.agents.llm_router.litellm.completion", return_value={"ok": True}
        ) as mock_completion,
    ):
        result = complete("orchestration", messages=[{"role": "user", "content": "hi"}])

    assert result == {"ok": True}
    assert mock_completion.call_args.kwargs["model"] == "openai/gpt-4o"
    assert mock_completion.call_args.kwargs["api_key"] == "sk-test"


def test_opencode_zen_routes_via_openai_compatible_api_base():
    settings = _settings(opencode_api_key="oc-test")

    with (
        patch("src.agents.llm_router.get_settings", return_value=settings),
        patch(
            "src.agents.llm_router.litellm.completion", return_value={"ok": True}
        ) as mock_completion,
    ):
        complete("orchestration", messages=[{"role": "user", "content": "hi"}])

    call_kwargs = mock_completion.call_args.kwargs
    assert call_kwargs["model"] == "openai/gpt-5.4-nano"
    assert call_kwargs["api_base"] == "https://opencode.ai/zen/v1"
    assert call_kwargs["api_key"] == "oc-test"


@pytest.fixture(autouse=True)
def _reset_tracing_state():
    import litellm

    import src.agents.llm_router as router

    original_flag = router._tracing_configured
    original_success = list(litellm.success_callback)
    original_failure = list(litellm.failure_callback)
    router._tracing_configured = False
    yield
    router._tracing_configured = original_flag
    litellm.success_callback[:] = original_success
    litellm.failure_callback[:] = original_failure


def test_tracing_not_configured_without_langsmith_key():
    import litellm

    settings = _settings()
    with (
        patch("src.agents.llm_router.get_settings", return_value=settings),
        patch("src.agents.llm_router.litellm.completion", return_value={"ok": True}),
    ):
        complete("orchestration", messages=[{"role": "user", "content": "hi"}])

    assert "langsmith" not in litellm.success_callback


def test_tracing_configured_once_when_langsmith_key_present():
    import litellm

    settings = _settings(langsmith_api_key="ls-test")
    with (
        patch("src.agents.llm_router.get_settings", return_value=settings),
        patch("src.agents.llm_router.litellm.completion", return_value={"ok": True}),
    ):
        complete("orchestration", messages=[{"role": "user", "content": "hi"}])
        complete("orchestration", messages=[{"role": "user", "content": "hi again"}])

    assert litellm.success_callback.count("langsmith") == 1
    assert litellm.failure_callback.count("langsmith") == 1


def test_load_routing_table_reads_real_routing_yaml():
    table = load_routing_table()
    assert set(table) == {"coding", "orchestration", "sentiment", "research", "chat"}
    assert table["coding"][-1] == ProviderModel("ollama", "deepseek-r1:latest")
    assert all(isinstance(pm, ProviderModel) for chain in table.values() for pm in chain)


def test_routing_table_is_hot_reloaded_from_disk(tmp_path):
    """Editing routing.yaml (no code change, no restart) must change complete()'s behavior on
    the very next call -- this is the whole point of externalizing it out of a hardcoded dict."""
    custom_yaml = tmp_path / "routing.yaml"
    custom_yaml.write_text(
        "orchestration:\n  - provider: ollama\n    model: custom-test-model:latest\n"
    )

    with (
        patch("src.agents.llm_router.ROUTING_CONFIG_PATH", custom_yaml),
        patch("src.agents.llm_router.get_settings", return_value=_settings()),
        patch(
            "src.agents.llm_router.litellm.completion", return_value={"ok": True}
        ) as mock_completion,
    ):
        complete("orchestration", messages=[{"role": "user", "content": "hi"}])

    assert mock_completion.call_args.kwargs["model"] == "ollama/custom-test-model:latest"
