"""spec 002 US7: the CEO's context scaffold (`ensure_research_scaffold`) resolves each scaffold
agent by real declared capability (`capability_registry.snapshot()`), not a hard-coded literal.
No DB, no LLM -- exercises `planner._resolve_scaffold_agent`/`ensure_research_scaffold` directly
against a synthetic registry, the same convention `test_plan_validation.py` uses for
`planner._validate`. Does not mutate the real `KNOWN_AGENTS`/`AGENT_META` module-level state.
"""

from src.orchestration.capability_registry import AgentSnapshotRow
from src.orchestration.planner import (
    _GeneratedPlan,
    _PlannedTask,
    _resolve_scaffold_agent,
    ensure_research_scaffold,
)


def _row(name: str, capabilities: list[str], enabled: bool = True) -> AgentSnapshotRow:
    return AgentSnapshotRow(
        name=name,
        agent_id=f"AGT-{name}",
        display_name=name,
        kind="scheduled",
        department="Market Intelligence",
        capabilities=capabilities,
        is_llm_backed=False,
        concurrency_limit=1,
        enabled=enabled,
        health="idle",
    )


def test_resolve_scaffold_agent_prefers_the_fallback_when_it_is_itself_a_valid_candidate() -> None:
    registry = [_row("news_agent", ["news_ingestion"]), _row("news_agent_v2", ["news_ingestion"])]
    assert _resolve_scaffold_agent(registry, "news_ingestion", "news_agent") == "news_agent"


def test_resolve_scaffold_agent_picks_a_match_when_the_fallback_is_not_registered() -> None:
    # The historical hard-coded literal no longer exists in the registry (e.g. renamed) --
    # resolution falls through to whichever enabled agent actually declares the capability,
    # rather than blindly returning a name with nothing behind it.
    registry = [_row("news_ingestion_agent_v2", ["news_ingestion"])]
    resolved = _resolve_scaffold_agent(registry, "news_ingestion", "news_agent")
    assert resolved == "news_ingestion_agent_v2"


def test_resolve_scaffold_agent_ignores_a_disabled_candidate() -> None:
    registry = [
        _row("news_agent", ["news_ingestion"], enabled=False),
        _row("news_agent_v2", ["news_ingestion"], enabled=True),
    ]
    assert _resolve_scaffold_agent(registry, "news_ingestion", "news_agent") == "news_agent_v2"


def test_resolve_scaffold_agent_falls_back_when_nothing_declares_the_capability() -> None:
    registry = [_row("unrelated_agent", ["some_other_capability"])]
    assert _resolve_scaffold_agent(registry, "news_ingestion", "news_agent") == "news_agent"


def test_ensure_research_scaffold_assigns_the_registered_agent_not_news_agent() -> None:
    # A second agent declaring news_ingestion is registered ahead of (and instead of) the
    # historical literal -- the scaffold must resolve to it, not silently keep using
    # "news_agent" regardless of what the registry actually says.
    registry = [
        _row("news_agent_v2", ["news_ingestion"]),
        _row("sentiment_agent", ["sentiment_analysis"]),
        _row("market_analyst", ["market_analysis"]),
        _row("portfolio_manager_agent", ["portfolio_read"]),
        _row("data_ingestion_agent", ["data_freshness"]),
        _row("ceo_agent", ["context_assembly"]),
    ]
    plan = _GeneratedPlan(
        can_plan=True,
        objective_classification="research",
        tasks=[
            _PlannedTask(
                key="strategy",
                objective="Generate a strategy",
                capability="strategy_generation",
                assigned_agent="strategy_generator",
                priority=5,
                expected_output="StrategyLogic",
            )
        ],
    )
    ensure_research_scaffold(plan, registry)
    news_tasks = [t for t in plan.tasks if t.capability == "news_ingestion"]
    assert len(news_tasks) == 1
    assert news_tasks[0].assigned_agent == "news_agent_v2"
