from contextlib import ExitStack
from unittest.mock import patch

import pytest

from src.agents.control import AgentHaltedError, set_agent_enabled
from src.agents.state import (
    BacktestMetrics,
    ComplianceVerdict,
    DeploymentRecommendation,
    EquityCurvePoint,
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
from src.core.db import get_session
from src.core.security import ROLE_SYSTEM_ADMINISTRATOR
from src.models.agent import AgentControlState
from tests.auth_helpers import cleanup_user, create_authenticated_user

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
_STRATEGY = StrategyLogic(
    hypothesis="Momentum breakout",
    asset_class="Equity",
    style="Intraday",
    universe=["TCS"],
    entry_conditions="Breakout above 20-day high",
    exit_conditions="Close below 10-day low",
    stop_loss="2%",
    take_profit="5%",
    position_sizing="1% risk",
    confidence_score=0.8,
)
_CODE = PythonCode(code="def run_backtest(data, config):\n    return {}\n", version_no=1)
_BACKTEST_METRICS = BacktestMetrics(sharpe_ratio=1.8, max_drawdown=-0.1)
_EQUITY_CURVE = [
    EquityCurvePoint(date="2024-01-01", equity=100_000.0),
    EquityCurvePoint(date="2024-01-02", equity=101_000.0),
]
_PASS_VERDICT = EvaluationVerdict(verdict="PASS")
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


def _mock_pipeline(
    *,
    validator_side_effect,
    ceo_side_effect=None,
    strategy_generator_side_effect=None,
    evaluator_side_effect=None,
    compliance_side_effect=None,
):
    compliance_kwargs = (
        {"side_effect": compliance_side_effect}
        if compliance_side_effect
        else {"return_value": {"compliance_verdict": _PASS_COMPLIANCE_VERDICT}}
    )
    ceo_kwargs = (
        {"side_effect": ceo_side_effect}
        if ceo_side_effect
        else {"return_value": {"research_directive": _DIRECTIVE, "strategy_rejection_count": 0}}
    )
    strategy_generator_kwargs = (
        {"side_effect": strategy_generator_side_effect}
        if strategy_generator_side_effect
        else {"return_value": {"strategy_logic": _STRATEGY, "strategy_rejection_count": 0}}
    )
    evaluator_kwargs = (
        {"side_effect": evaluator_side_effect}
        if evaluator_side_effect
        else {"return_value": {"evaluation_verdict": _PASS_VERDICT}}
    )
    return (
        patch("src.agents.graph.ceo_agent_node", **ceo_kwargs),
        patch("src.agents.graph.market_analyst_node", return_value={"market_context": _CONTEXT}),
        patch("src.agents.graph.strategy_generator_node", **strategy_generator_kwargs),
        patch("src.agents.graph.python_code_generator_node", return_value={"python_code": _CODE}),
        patch("src.agents.graph.compliance_node", **compliance_kwargs),
        patch("src.agents.graph.python_validator_node", side_effect=validator_side_effect),
        patch(
            "src.agents.graph.backtesting_node",
            return_value={"backtest_metrics": _BACKTEST_METRICS, "equity_curve": _EQUITY_CURVE},
        ),
        patch("src.agents.graph.evaluator_node", **evaluator_kwargs),
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
    )


def _invoke_with_patches(patches, state):
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        from src.agents.graph import build_graph

        return build_graph().invoke(state)


def _passing_validator(state):
    return {
        "validation_result": ValidationResult(status="Pass"),
        "code_validation_retry_count": 0,
    }


def test_graph_happy_path_reaches_deployment_recommendation():
    patches = _mock_pipeline(validator_side_effect=_passing_validator)
    result = _invoke_with_patches(patches, TradingOSGraphState(thread_id="t1"))

    assert result["validation_result"].status == "Pass"
    assert result["research_directive"].market_regime == "Bullish"
    assert result["deployment_recommendation"].recommended_status == "PaperTrading"


def test_graph_retries_validator_then_passes():
    call_count = {"n": 0}

    def validator(state):
        call_count["n"] += 1
        if call_count["n"] < 2:
            return {
                "validation_result": ValidationResult(status="Fail", feedback="bad code"),
                "code_validation_retry_count": state.code_validation_retry_count + 1,
            }
        return {
            "validation_result": ValidationResult(status="Pass"),
            "code_validation_retry_count": state.code_validation_retry_count,
        }

    patches = _mock_pipeline(validator_side_effect=validator)
    result = _invoke_with_patches(patches, TradingOSGraphState(thread_id="t1"))

    assert result["validation_result"].status == "Pass"
    assert call_count["n"] == 2


def test_graph_fails_gracefully_after_max_retries():
    def validator(state):
        return {
            "validation_result": ValidationResult(status="Fail", feedback="always bad"),
            "code_validation_retry_count": state.code_validation_retry_count + 1,
        }

    patches = _mock_pipeline(validator_side_effect=validator)
    result = _invoke_with_patches(patches, TradingOSGraphState(thread_id="t1"))

    assert result["validation_result"].status == "Fail"
    assert result["code_validation_retry_count"] == 3


def test_graph_escalates_to_ceo_after_five_consecutive_rejections():
    """REL-005 E5.2: strategy_generator_node increments strategy_rejection_count on every FAIL
    verdict it receives; once that count reaches 5, route_after_evaluation escalates back to
    ceo_agent_node instead of looping strategy_generator again -- and ceo_agent_node resets the
    counter on that re-entry, giving the escalated cycle a fresh 5-strikes budget."""
    tracker = {"ceo_calls": 0}

    def ceo_side_effect(state):
        tracker["ceo_calls"] += 1
        return {"research_directive": _DIRECTIVE, "strategy_rejection_count": 0}

    def strategy_generator_side_effect(state):
        rejection_count = state.strategy_rejection_count
        if state.evaluation_verdict is not None and state.evaluation_verdict.verdict == "FAIL":
            rejection_count += 1
        return {"strategy_logic": _STRATEGY, "strategy_rejection_count": rejection_count}

    def evaluator_side_effect(state):
        # Fails every time until the escalation has actually happened once (proven by a 2nd
        # ceo_agent invocation), then passes so the test terminates instead of escalating forever.
        if tracker["ceo_calls"] >= 2:
            return {"evaluation_verdict": _PASS_VERDICT}
        return {
            "evaluation_verdict": EvaluationVerdict(
                verdict="FAIL",
                failure_reasons=["Sharpe too low"],
                feedback_for_strategy_generator="try a different universe",
            )
        }

    patches = _mock_pipeline(
        validator_side_effect=_passing_validator,
        ceo_side_effect=ceo_side_effect,
        strategy_generator_side_effect=strategy_generator_side_effect,
        evaluator_side_effect=evaluator_side_effect,
    )
    result = _invoke_with_patches(patches, TradingOSGraphState(thread_id="t1"))

    assert tracker["ceo_calls"] == 2
    assert result["deployment_recommendation"].recommended_status == "PaperTrading"


def test_graph_ends_immediately_on_a_compliance_block():
    """REL-006: a real compliance Block must stop the pipeline before python_validator/
    backtesting ever run -- never silently proceed past a compliance failure."""
    validator_called = {"n": 0}

    def validator(state):
        validator_called["n"] += 1
        return {
            "validation_result": ValidationResult(status="Pass"),
            "code_validation_retry_count": 0,
        }

    block_verdict = ComplianceVerdict(
        verdict="Block",
        violations=["SEBI_POSITION_LIMIT: exceeded"],
        naked_options_checked=False,
        position_limit_checked=True,
        circuit_filter_checked=False,
        narrative="blocked",
    )
    patches = _mock_pipeline(
        validator_side_effect=validator,
        compliance_side_effect=lambda state: {"compliance_verdict": block_verdict},
    )
    result = _invoke_with_patches(patches, TradingOSGraphState(thread_id="t1"))

    assert result["compliance_verdict"].verdict == "Block"
    assert validator_called["n"] == 0
    assert result.get("deployment_recommendation") is None


def test_graph_topology_includes_compliance_between_code_generator_and_validator():
    from src.agents.graph import build_graph

    representation = build_graph().get_graph()
    node_ids = set(representation.nodes)
    assert "compliance" in node_ids

    edges = {(e.source, e.target) for e in representation.edges}
    assert ("python_code_generator", "compliance") in edges
    assert ("compliance", "python_validator") in edges


def _clear_control_row(agent_name: str) -> None:
    with get_session() as session:
        session.query(AgentControlState).filter(AgentControlState.agent_name == agent_name).delete()
        session.commit()


def test_halt_on_entry_stops_a_disabled_node_before_its_real_logic_runs():
    """REL-019 E19.2 (ADR 11): a disabled graph node must never execute its real logic -- proven
    here directly (not via a real LLM-costing end-to-end run) by disabling `strategy_generator`
    in the real agent_control_state table, then asserting build_graph().invoke() raises
    AgentHaltedError before the mocked strategy_generator_node is ever called."""
    call_count = {"n": 0}

    def strategy_generator_side_effect(state):
        call_count["n"] += 1
        return {"strategy_logic": _STRATEGY, "strategy_rejection_count": 0}

    user_id, _token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        with get_session() as session:
            set_agent_enabled(
                session,
                agent_name="strategy_generator",
                enabled=False,
                reason="unit test halt",
                updated_by_user_id=user_id,
            )
            session.commit()

        patches = _mock_pipeline(
            validator_side_effect=_passing_validator,
            strategy_generator_side_effect=strategy_generator_side_effect,
        )
        with pytest.raises(AgentHaltedError) as exc_info:
            _invoke_with_patches(patches, TradingOSGraphState(thread_id="t1"))

        assert exc_info.value.agent_name == "strategy_generator"
        assert exc_info.value.reason == "unit test halt"
        assert call_count["n"] == 0  # the real node logic never ran
    finally:
        _clear_control_row("strategy_generator")
        cleanup_user(user_id)


def test_reenabling_a_halted_agent_lets_the_next_run_proceed_normally():
    user_id, _token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        with get_session() as session:
            set_agent_enabled(
                session,
                agent_name="market_analyst",
                enabled=False,
                reason="temporary",
                updated_by_user_id=user_id,
            )
            session.commit()
            set_agent_enabled(
                session,
                agent_name="market_analyst",
                enabled=True,
                reason=None,
                updated_by_user_id=user_id,
            )
            session.commit()

        patches = _mock_pipeline(validator_side_effect=_passing_validator)
        result = _invoke_with_patches(patches, TradingOSGraphState(thread_id="t1"))
        assert result["deployment_recommendation"].recommended_status == "PaperTrading"
    finally:
        _clear_control_row("market_analyst")
        cleanup_user(user_id)
