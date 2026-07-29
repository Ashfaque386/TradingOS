"""Agent Console API integration test (Phase 4 Epic E4.3): the read/topology/prompt-registry
endpoints wired in src/api/routers/agents.py, against the real FastAPI app + real
prompt_registry.py files on disk. Does NOT trigger a real graph run (POST /research/trigger) --
that's covered by hand-verified end-to-end runs elsewhere in this session (real LLM calls that
can take 10+ minutes here via the Ollama fallback path, impractical for a routine test run);
this focuses on the deterministic, fast parts: topology introspection, run history reads, and a
real, reversible prompt hot-swap.
"""

from fastapi.testclient import TestClient

from src.agents.prompt_registry import get_active_prompt
from src.api.main import app

client = TestClient(app)


def test_graph_topology_reflects_the_real_compiled_graph():
    response = client.get("/api/v1/agents/graph")
    assert response.status_code == 200
    body = response.json()
    node_ids = {n["id"] for n in body["nodes"]}
    assert {
        "ceo_agent",
        "market_analyst",
        "strategy_generator",
        "python_code_generator",
        "python_validator",
        "backtesting",
        "evaluator",
        "optimization",
        "risk_manager",
        "deployment",
    } <= node_ids
    retry_edges = [
        e
        for e in body["edges"]
        if e["source"] == "python_validator" and e["target"] == "python_code_generator"
    ]
    assert retry_edges and retry_edges[0]["conditional"] is True


def test_runs_list_returns_only_root_runs():
    response = client.get("/api/v1/agents/runs")
    assert response.status_code == 200
    for run in response.json():
        assert run["agent_name"] == "TradingOSGraph"


def test_prompts_list_matches_the_real_registry_file():
    response = client.get("/api/v1/agents/prompts")
    assert response.status_code == 200
    slugs = {p["agent_slug"] for p in response.json()}
    assert {
        "ceo_agent",
        "market_analyst_agent",
        "strategy_generator_agent",
        "python_code_generator_agent",
        "python_validator_agent",
    } <= slugs


def test_prompt_version_hot_swap_is_real_and_reversible():
    slug = "python_code_generator_agent"
    original = client.get("/api/v1/agents/prompts").json()
    original_entry = next(p for p in original if p["agent_slug"] == slug)
    original_version = original_entry["active_version"]
    assert original_version in original_entry["available_versions"]
    other_version = next(v for v in original_entry["available_versions"] if v != original_version)

    try:
        swap_response = client.put(
            f"/api/v1/agents/prompts/{slug}/active-version", json={"version": other_version}
        )
        assert swap_response.status_code == 200
        assert swap_response.json()["active_version"] == other_version
        # get_active_prompt() re-reads registry.yaml fresh -- confirms the swap actually took
        # effect on the real hot-reload path every agent node calls, not just the API response.
        content_at_other_version = get_active_prompt(slug)

        version_content_response = client.get(
            f"/api/v1/agents/prompts/{slug}/versions/{other_version}"
        )
        assert version_content_response.status_code == 200
        assert version_content_response.json()["content"] == content_at_other_version
    finally:
        restore_response = client.put(
            f"/api/v1/agents/prompts/{slug}/active-version", json={"version": original_version}
        )
        assert restore_response.status_code == 200
        assert restore_response.json()["active_version"] == original_version
