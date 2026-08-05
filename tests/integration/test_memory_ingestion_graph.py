"""REL-025 E25.3: proves the real graph topology -- not just `ingest_strategy_outcome` called
directly (tests/integration/test_rag_pipeline_e2e.py's existing coverage) -- actually calls it
after a real FAIL verdict. Every node except `memory_ingest_node` itself is mocked (same harness
style as tests/unit/test_graph.py), so this is a real `build_graph().invoke()` run against the
real Postgres (`_halt_on_entry`'s own DB check) and real Qdrant/embeddings (the one node
deliberately left unmocked), not an end-to-end LLM run.
"""

import uuid
from contextlib import ExitStack
from unittest.mock import patch

from qdrant_client import QdrantClient

from src.agents.graph import build_graph
from src.agents.nodes.strategy_generator import strategy_generator_node
from src.agents.state import (
    BacktestMetrics,
    ComplianceVerdict,
    DeploymentRecommendation,
    EvaluationVerdict,
    MarketContext,
    OptimizationResult,
    PythonCode,
    ResearchDirective,
    RiskAssessment,
    StrategyLogic,
    TradingOSGraphState,
    ValidationResult,
)
from src.core.config import get_settings
from src.memory.collections import bootstrap_collections

_DIRECTIVE = ResearchDirective(
    market_regime="Bullish",
    priority_sectors=["IT"],
    strategy_themes=["Momentum"],
    risk_tolerance="Medium",
    participating_agents=["MarketAnalystAgent"],
    expected_outcomes="Find momentum plays",
)
_CONTEXT = MarketContext(
    market_regime="Bullish",
    sector_rankings=["IT"],
    volatility_assessment="Low",
    macro_outlook="Stable",
    confidence_score=0.7,
    insights=["Momentum favorable"],
)
_CODE = PythonCode(code="def run_backtest(data, config):\n    return {}\n", version_no=1)
_BACKTEST_METRICS = BacktestMetrics(sharpe_ratio=0.1, max_drawdown=0.28)
_PASS_COMPLIANCE_VERDICT = ComplianceVerdict(
    verdict="Pass",
    naked_options_checked=False,
    position_limit_checked=False,
    circuit_filter_checked=False,
    narrative="ok",
)
_OPTIMIZATION_RESULT = OptimizationResult(passed=True, notes="robust")
_RISK_ASSESSMENT = RiskAssessment(
    decision="ApproveWithRestrictions",
    kill_switch_tripped=False,
    naked_options_checked=False,
    narrative="ok",
)
_DEPLOYMENT_RECOMMENDATION = DeploymentRecommendation(
    recommended_status="PaperTrading", rationale="go"
)


def test_graph_wiring_ingests_a_real_fail_verdict_into_qdrant_and_it_is_retrievable():
    marker = f"unique-rel025-marker-{uuid.uuid4().hex[:8]}"
    thread_id = f"rel025-{marker}"
    strategy = StrategyLogic(
        hypothesis=f"Overfit RSI mean reversion on Bank Nifty {marker}",
        asset_class="Equity",
        style="Intraday",
        universe=["RELIANCE"],
        entry_conditions="RSI < 30",
        exit_conditions="RSI > 70",
        stop_loss="2%",
        take_profit="4%",
        position_sizing="1% risk",
        confidence_score=0.5,
    )
    fail_verdict = EvaluationVerdict(
        verdict="FAIL",
        failure_reasons=["Sharpe too low", "Overfit to a single regime"],
        feedback_for_strategy_generator="try a different universe",
    )
    pass_verdict = EvaluationVerdict(verdict="PASS")

    client = QdrantClient(url=get_settings().qdrant_url)
    bootstrap_collections(client)

    evaluator_calls = {"n": 0}

    def evaluator_side_effect(state):
        # FAIL exactly once (real memory_ingest ingestion), then PASS so the graph terminates
        # instead of looping the real Strategy Generator/Code Generator/Compliance/Validator
        # chain a second time.
        evaluator_calls["n"] += 1
        if evaluator_calls["n"] == 1:
            return {"evaluation_verdict": fail_verdict}
        return {"evaluation_verdict": pass_verdict}

    patches = [
        patch(
            "src.agents.graph.ceo_agent_node",
            return_value={"research_directive": _DIRECTIVE, "strategy_rejection_count": 0},
        ),
        patch("src.agents.graph.market_analyst_node", return_value={"market_context": _CONTEXT}),
        patch(
            "src.agents.graph.strategy_generator_node",
            return_value={"strategy_logic": strategy, "strategy_rejection_count": 0},
        ),
        patch(
            "src.agents.graph.python_code_generator_node",
            return_value={"python_code": _CODE, "strategy_version_id": f"{thread_id}-v1"},
        ),
        patch(
            "src.agents.graph.compliance_node",
            return_value={"compliance_verdict": _PASS_COMPLIANCE_VERDICT},
        ),
        patch(
            "src.agents.graph.python_validator_node",
            return_value={
                "validation_result": ValidationResult(status="Pass"),
                "code_validation_retry_count": 0,
            },
        ),
        patch(
            "src.agents.graph.backtesting_node",
            return_value={"backtest_metrics": _BACKTEST_METRICS, "equity_curve": []},
        ),
        patch("src.agents.graph.evaluator_node", side_effect=evaluator_side_effect),
        # memory_ingest_node is deliberately NOT mocked -- the real node under test, hitting real
        # Qdrant/embeddings.
        patch(
            "src.agents.graph.optimization_node",
            return_value={"optimization_result": _OPTIMIZATION_RESULT},
        ),
        patch(
            "src.agents.graph.risk_manager_node",
            return_value={"risk_assessment": _RISK_ASSESSMENT},
        ),
        patch(
            "src.agents.graph.deployment_node",
            return_value={"deployment_recommendation": _DEPLOYMENT_RECOMMENDATION},
        ),
    ]

    seeded_point_ids: list[str] = []
    try:
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            result = build_graph().invoke(TradingOSGraphState(thread_id=thread_id))

        assert evaluator_calls["n"] == 2  # one real FAIL, then a real PASS
        assert result["deployment_recommendation"].recommended_status == "PaperTrading"

        # The real exit criterion: the graph itself (not a direct call) produced a real Qdrant
        # point for the FAIL verdict, findable by the real strategy_id (thread_id) this run used.
        points, _ = client.scroll(
            collection_name="trading_strategies", limit=200, with_payload=True
        )
        matches = [p for p in points if (p.payload or {}).get("strategy_id") == thread_id]
        assert len(matches) == 1, f"expected exactly one real ingested point for {thread_id}"
        seeded_point_ids = [str(matches[0].id)]
        payload = matches[0].payload
        assert payload["strategy_version_id"] == f"{thread_id}-v1"
        assert payload["status"] == "deprecated"
        assert payload["failure_reason"] == "Sharpe too low; Overfit to a single regime"
        assert payload["sharpe_ratio"] == 0.1
        assert payload["max_drawdown"] == 0.28

        # REL-025 exit criterion: the next real Strategy Generator pass (not mocked this time)
        # retrieves the just-ingested failure via real RAG search and surfaces it in the LLM
        # prompt -- same retrieval-side proof test_rag_pipeline_e2e.py's own test already
        # established for a directly-ingested point, now proven for a graph-ingested one.
        # ingest_strategy_outcome's Qdrant payload (DB-023) never stores the hypothesis text
        # itself, only strategy_id/strategy_version_id/asset_class/sharpe/drawdown/status/
        # failure_reason -- so the query text must closely match the embedded hypothesis (for a
        # reliable top-5 rank against this shared, never-purged collection's accumulated points
        # from other tests) and the assertion must check for the real, retrievable strategy_id
        # field (thread_id, which contains the marker), not the hypothesis text itself.
        retrieval_directive = ResearchDirective(
            market_regime="Bullish",
            priority_sectors=["Banking"],
            strategy_themes=["Mean Reversion"],
            risk_tolerance="Medium",
            participating_agents=["MarketAnalystAgent"],
            expected_outcomes="Overfit RSI mean reversion on Bank Nifty",
        )
        with patch("src.agents.nodes.strategy_generator.complete") as mock_complete:
            mock_complete.return_value.choices[0].message.content = (
                '{"hypothesis": "New idea", "asset_class": "Equity", "style": "Intraday", '
                '"universe": ["RELIANCE"], "entry_conditions": "x", "exit_conditions": "y", '
                '"stop_loss": "2%", "take_profit": "4%", "position_sizing": "1%", '
                '"confidence_score": 0.6}'
            )
            strategy_generator_node(
                TradingOSGraphState(
                    thread_id="retrieval-check", research_directive=retrieval_directive
                )
            )

        sent_messages = mock_complete.call_args.kwargs["messages"]
        user_content = sent_messages[1]["content"]
        assert thread_id in user_content, (
            "The graph-ingested failed strategy's real strategy_id was not surfaced in the next "
            "Strategy Generator pass's prompt -- RAG retrieval did not deprioritize/exclude it "
            "as intended."
        )
    finally:
        if seeded_point_ids:
            client.delete(collection_name="trading_strategies", points_selector=seeded_point_ids)
