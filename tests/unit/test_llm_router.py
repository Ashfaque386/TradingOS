from unittest.mock import MagicMock, patch

import pytest

from src.agents.llm_router import (
    NoProviderAvailableError,
    ProviderModel,
    build_fallback_chain,
    complete,
    fetch_langsmith_trace_url,
    is_configured,
    load_routing_table,
    pop_last_langsmith_run_id,
)
from src.core.config import Settings


def _settings(**overrides) -> Settings:
    """`vault_addr=None` by default: `is_configured`/`_litellm_kwargs` now check Vault first
    (REL-002 E2.2), so without this these "unit" tests would silently depend on whatever this
    dev machine's real Vault happens to have stored for LLM provider keys — the exact same
    live-Vault test-isolation risk already caught and fixed for test_broker_factory.py.

    `langsmith_api_key=None` by default for the same reason, discovered by this same class of
    bug during REL-009 E9.2: `_configure_tracing()` calls
    `os.environ.setdefault("LANGSMITH_API_KEY", ...)` as a real, intentional production side
    effect (litellm's LangSmith callback reads it from `os.environ`, not from Settings) -- but
    `Settings(_env_file=None, ...)` still reads real
    process environment variables regardless of `_env_file`, so once any earlier test in this
    same pytest process configures tracing with a fake key, that fake key leaks into every
    later `_settings()` call's `langsmith_api_key` unless explicitly overridden back to None.

    `hf_token`/`opencode_api_key`/every other provider key default to None for the same reason
    -- confirmed 2026-07-31: this repo's real `.env` has real HF_TOKEN and OPENCODE_API_KEY
    values configured, and individual tests here passed reliably alone but failed
    unpredictably (different provider each run) as part of the full suite -- e.g.
    `is_configured("huggingface", _settings())` returning True, or a fallback chain including
    an unexpected "opencode" entry. `Settings(_env_file=None, ...)` does not reliably isolate
    every field from the real `.env` file under full-suite load (confirmed via direct,
    repeated manual testing: identical construction returns the correct None in isolation but
    an inconsistent real value under full-suite timing/ordering -- root cause not fully
    pinned down, but the leak is real and empirically reproducible). Defensively defaulting
    every provider-key-shaped field here, not just whichever field happened to leak in the
    last observed failure, closes the whole class of bug rather than chasing it field-by-field
    across future runs."""
    overrides.setdefault("vault_addr", None)
    overrides.setdefault("langsmith_api_key", None)
    overrides.setdefault("hf_token", None)
    overrides.setdefault("openai_api_key", None)
    overrides.setdefault("anthropic_api_key", None)
    overrides.setdefault("deepseek_api_key", None)
    overrides.setdefault("gemini_api_key", None)
    overrides.setdefault("opencode_api_key", None)
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
    router._last_langsmith_run_id.set(None)
    yield
    router._tracing_configured = original_flag
    litellm.success_callback[:] = original_success
    litellm.failure_callback[:] = original_failure
    router._last_langsmith_run_id.set(None)


@pytest.fixture(autouse=True)
def _reset_hf_usage_tracker():
    """The huggingface usage tracker is a real module-level singleton (see its own docstring for
    why) -- without resetting it, a test that records usage would leak real accumulated tokens
    into every later test in the same pytest process, the same class of test-isolation bug
    already caught and fixed for _tracing_configured/langsmith_api_key above."""
    import src.agents.llm_router as router

    router._hf_usage_tracker = router._HFUsageTracker()
    yield
    router._hf_usage_tracker = router._HFUsageTracker()


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


def test_complete_does_not_attach_langsmith_metadata_when_tracing_unconfigured():
    settings = _settings()
    with (
        patch("src.agents.llm_router.get_settings", return_value=settings),
        patch(
            "src.agents.llm_router.litellm.completion", return_value={"ok": True}
        ) as mock_completion,
    ):
        complete("orchestration", messages=[{"role": "user", "content": "hi"}])

    assert "metadata" not in mock_completion.call_args.kwargs
    assert pop_last_langsmith_run_id() is None


def test_complete_attaches_a_real_metadata_id_and_sets_it_for_pop_when_tracing_configured():
    settings = _settings(langsmith_api_key="ls-test")
    with (
        patch("src.agents.llm_router.get_settings", return_value=settings),
        patch(
            "src.agents.llm_router.litellm.completion", return_value={"ok": True}
        ) as mock_completion,
    ):
        complete("orchestration", messages=[{"role": "user", "content": "hi"}])

    run_id = mock_completion.call_args.kwargs["metadata"]["id"]
    assert run_id  # a real, non-empty uuid4 string
    # pop_last_langsmith_run_id() reads AND clears -- a second call must return None.
    assert pop_last_langsmith_run_id() == run_id
    assert pop_last_langsmith_run_id() is None


def test_pop_last_langsmith_run_id_defaults_to_none():
    assert pop_last_langsmith_run_id() is None


def test_fetch_langsmith_trace_url_returns_none_without_a_configured_key():
    settings = _settings()
    with patch("src.agents.llm_router.get_settings", return_value=settings):
        assert fetch_langsmith_trace_url("some-run-id") is None


def test_fetch_langsmith_trace_url_strips_query_string_and_returns_the_base_url():
    settings = _settings(langsmith_api_key="ls-test")

    class _FakeRun:
        url = "https://smith.langchain.com/o/org/projects/p/proj/r/abc?trace_id=abc&start_time=x"

    fake_client = MagicMock()
    fake_client.read_run.return_value = _FakeRun()

    with (
        patch("src.agents.llm_router.get_settings", return_value=settings),
        patch("langsmith.Client", return_value=fake_client),
    ):
        url = fetch_langsmith_trace_url("abc")

    assert url == "https://smith.langchain.com/o/org/projects/p/proj/r/abc"


def test_sentiment_chain_prefers_huggingface_over_local_ollama():
    """REL-009 (2026-07-30 user request): huggingface must come before ollama in every task-type
    chain now that HF Pro billing is enabled -- `sentiment` was the one real inconsistency
    (ollama listed first) fixed in routing.yaml alongside this test."""
    table = load_routing_table()
    providers = [pm.provider for pm in table["sentiment"]]
    assert providers.index("huggingface") < providers.index("ollama")


def test_huggingface_call_gets_a_default_max_tokens_cap():
    settings = _settings(hf_token="hf-test", hf_max_tokens_per_call=777)
    with (
        patch("src.agents.llm_router.get_settings", return_value=settings),
        patch(
            "src.agents.llm_router.litellm.completion", return_value={"ok": True}
        ) as mock_completion,
    ):
        complete("sentiment", messages=[{"role": "user", "content": "hi"}])

    assert mock_completion.call_args.kwargs["max_tokens"] == 777


def test_huggingface_call_does_not_override_a_caller_supplied_max_tokens():
    settings = _settings(hf_token="hf-test", hf_max_tokens_per_call=777)
    with (
        patch("src.agents.llm_router.get_settings", return_value=settings),
        patch(
            "src.agents.llm_router.litellm.completion", return_value={"ok": True}
        ) as mock_completion,
    ):
        complete("sentiment", messages=[{"role": "user", "content": "hi"}], max_tokens=42)

    assert mock_completion.call_args.kwargs["max_tokens"] == 42


def test_successful_huggingface_call_records_real_token_usage():
    import src.agents.llm_router as router

    settings = _settings(hf_token="hf-test")
    fake_response = MagicMock()
    fake_response.usage.total_tokens = 123

    with (
        patch("src.agents.llm_router.get_settings", return_value=settings),
        patch("src.agents.llm_router.litellm.completion", return_value=fake_response),
    ):
        complete("sentiment", messages=[{"role": "user", "content": "hi"}])

    assert router._hf_usage_tracker.tokens_used_today() == 123


def test_huggingface_is_unconfigured_once_daily_token_budget_is_exhausted():
    import src.agents.llm_router as router

    settings = _settings(hf_token="hf-test", hf_daily_token_budget=100)
    router._hf_usage_tracker.record(100)  # already at budget before this call

    assert is_configured("huggingface", settings) is False

    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs["model"])
        return {"choices": [{"message": {"content": "ok"}}]}

    with (
        patch("src.agents.llm_router.get_settings", return_value=settings),
        patch("src.agents.llm_router.litellm.completion", side_effect=fake_completion),
    ):
        complete("sentiment", messages=[{"role": "user", "content": "hi"}])

    # huggingface skipped entirely -- falls straight through to ollama, the chain's last resort.
    assert calls == ["ollama/deepseek-r1:latest"]


def test_huggingface_budget_resets_on_a_new_utc_day():
    import datetime as dt

    import src.agents.llm_router as router

    router._hf_usage_tracker.record(500)
    assert router._hf_usage_tracker.tokens_used_today() == 500

    router._hf_usage_tracker._day = dt.date(2020, 1, 1)  # force a stale, definitely-past day

    assert router._hf_usage_tracker.tokens_used_today() == 0


def test_fetch_langsmith_trace_url_retries_then_fails_soft_without_raising():
    settings = _settings(langsmith_api_key="ls-test")
    fake_client = MagicMock()
    fake_client.read_run.side_effect = RuntimeError("not indexed yet")

    with (
        patch("src.agents.llm_router.get_settings", return_value=settings),
        patch("langsmith.Client", return_value=fake_client),
        patch("src.agents.llm_router.time.sleep"),  # don't actually wait in a unit test
    ):
        url = fetch_langsmith_trace_url("abc", attempts=3, delay_seconds=0)

    assert url is None
    assert fake_client.read_run.call_count == 3
