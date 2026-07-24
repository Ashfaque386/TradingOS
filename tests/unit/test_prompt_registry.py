import pytest

from src.agents.prompt_registry import PromptNotFoundError, get_active_prompt, get_prompt_id


@pytest.mark.parametrize(
    "agent_slug,prompt_id",
    [
        ("ceo_agent", "PMPT-001"),
        ("market_analyst_agent", "PMPT-002"),
        ("strategy_generator_agent", "PMPT-003"),
        ("python_code_generator_agent", "PMPT-004"),
        ("python_validator_agent", "PMPT-005"),
        ("ceo_agent_task", "PMPT-027"),
        ("market_analyst_agent_task", "PMPT-028"),
        ("strategy_generator_agent_task", "PMPT-029"),
        ("python_code_generator_agent_task", "PMPT-030"),
        ("memory_agent_task", "PMPT-031"),
    ],
)
def test_get_prompt_id_matches_registry(agent_slug, prompt_id):
    assert get_prompt_id(agent_slug) == prompt_id


def test_get_active_prompt_returns_nonempty_text():
    prompt = get_active_prompt("ceo_agent")
    assert prompt.startswith("You are the CEO Agent of TradingOS")
    assert len(prompt) > 100


def test_get_active_prompt_unknown_agent_raises():
    with pytest.raises(PromptNotFoundError):
        get_active_prompt("nonexistent_agent")


def test_get_prompt_id_unknown_agent_raises():
    with pytest.raises(PromptNotFoundError):
        get_prompt_id("nonexistent_agent")


def test_task_prompts_are_real_format_templates_not_static_text():
    """PMPT-027..031 (found unversioned during the 2026-07-24 Phase 9 §6 checklist audit --
    every node's user/task prompt was a hardcoded f-string) hold a `.format()` template, not a
    frozen literal -- confirms each one actually has at least one placeholder and renders
    without a KeyError for the exact keyword set its node passes."""
    cases = {
        "ceo_agent_task": {"schema": {}},
        "market_analyst_agent_task": {
            "directive_json": "none",
            "missing_summary": "nothing -- all sources live",
            "schema": {},
        },
        "strategy_generator_agent_task": {
            "directive_json": "none",
            "context_json": "none",
            "past_strategies": [],
            "rejection_feedback": "",
            "schema": {},
        },
        "python_code_generator_agent_task": {"strategy_json": "{}", "templates": []},
        "memory_agent_task": {"count": 0, "payloads": []},
    }
    for slug, kwargs in cases.items():
        template = get_active_prompt(slug)
        assert "{" in template  # a real placeholder, not static text
        # .format() raises KeyError if any placeholder in the template has no matching kwarg --
        # a clean call proves every placeholder was actually satisfied (substituted values like
        # `{}` for an empty dict legitimately contain braces themselves, so checking the
        # *rendered* text for a leftover "{" would be a false signal either way).
        template.format(**kwargs)


def test_all_five_e23_agents_have_distinct_nonempty_prompts():
    slugs = [
        "ceo_agent",
        "market_analyst_agent",
        "strategy_generator_agent",
        "python_code_generator_agent",
        "python_validator_agent",
    ]
    prompts = [get_active_prompt(slug) for slug in slugs]
    assert len(set(prompts)) == len(slugs)  # all distinct
    assert all(len(p) > 100 for p in prompts)
