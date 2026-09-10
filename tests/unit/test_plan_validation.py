"""Unit tests for the CEO planner's deterministic plan validation (spec T031, FR-007).

No DB, no LLM -- exercises ``planner._validate`` directly against a synthetic capability map.
"""

import pytest

from src.orchestration.planner import PlanValidationError, _GeneratedPlan, _PlannedTask, _validate

_KNOWN = {
    "market_analyst": {"market_analysis"},
    "news_agent": {"news_ingestion"},
    "sentiment_agent": {"sentiment_analysis"},
    "python_validator": {"code_validation"},
    "compliance": {"compliance_check"},
    "backtesting": {"backtesting"},
    "evaluator": {"strategy_evaluation"},
    "risk_manager": {"risk_assessment"},
}


def _plan(*tasks: _PlannedTask) -> _GeneratedPlan:
    return _GeneratedPlan(can_plan=True, tasks=list(tasks))


def test_accepts_a_well_formed_plan():
    plan = _plan(
        _PlannedTask(
            key="t1",
            objective="market",
            capability="market_analysis",
            assigned_agent="market_analyst",
        ),
        _PlannedTask(
            key="t2", objective="news", capability="news_ingestion", assigned_agent="news_agent"
        ),
        _PlannedTask(
            key="t3",
            objective="sentiment",
            capability="sentiment_analysis",
            assigned_agent="sentiment_agent",
            depends_on=["t2"],
        ),
    )
    _validate(plan, _KNOWN)  # no raise


def test_rejects_unknown_agent():
    plan = _plan(
        _PlannedTask(key="t1", objective="x", capability="market_analysis", assigned_agent="nope")
    )
    with pytest.raises(PlanValidationError, match="unknown agent"):
        _validate(plan, _KNOWN)


def test_rejects_capability_mismatch():
    plan = _plan(
        _PlannedTask(
            key="t1", objective="x", capability="news_ingestion", assigned_agent="market_analyst"
        )
    )
    with pytest.raises(PlanValidationError, match="does not declare capability"):
        _validate(plan, _KNOWN)


def test_rejects_out_of_plan_dependency():
    plan = _plan(
        _PlannedTask(
            key="t1",
            objective="x",
            capability="market_analysis",
            assigned_agent="market_analyst",
            depends_on=["ghost"],
        )
    )
    with pytest.raises(PlanValidationError, match="not an in-plan task"):
        _validate(plan, _KNOWN)


def test_rejects_dependency_cycle():
    plan = _plan(
        _PlannedTask(
            key="t1",
            objective="a",
            capability="market_analysis",
            assigned_agent="market_analyst",
            depends_on=["t2"],
        ),
        _PlannedTask(
            key="t2",
            objective="b",
            capability="news_ingestion",
            assigned_agent="news_agent",
            depends_on=["t1"],
        ),
    )
    with pytest.raises(PlanValidationError, match="cycle"):
        _validate(plan, _KNOWN)


def test_rejects_reordered_safety_chain():
    # backtesting must depend (transitively) on compliance_check must depend on code_validation.
    plan = _plan(
        _PlannedTask(
            key="v",
            objective="validate",
            capability="code_validation",
            assigned_agent="python_validator",
        ),
        _PlannedTask(
            key="b",
            objective="backtest",
            capability="backtesting",
            assigned_agent="backtesting",
            depends_on=["v"],
        ),
        _PlannedTask(
            key="c",
            objective="comply",
            capability="compliance_check",
            assigned_agent="compliance",
            depends_on=["v"],
        ),
    )
    with pytest.raises(PlanValidationError, match="safety order"):
        _validate(plan, _KNOWN)


def test_accepts_correctly_ordered_safety_chain():
    plan = _plan(
        _PlannedTask(
            key="v",
            objective="validate",
            capability="code_validation",
            assigned_agent="python_validator",
        ),
        _PlannedTask(
            key="c",
            objective="comply",
            capability="compliance_check",
            assigned_agent="compliance",
            depends_on=["v"],
        ),
        _PlannedTask(
            key="b",
            objective="backtest",
            capability="backtesting",
            assigned_agent="backtesting",
            depends_on=["c"],
        ),
        _PlannedTask(
            key="e",
            objective="evaluate",
            capability="strategy_evaluation",
            assigned_agent="evaluator",
            depends_on=["b"],
        ),
        _PlannedTask(
            key="r",
            objective="risk",
            capability="risk_assessment",
            assigned_agent="risk_manager",
            depends_on=["e"],
        ),
    )
    _validate(plan, _KNOWN)  # no raise


def test_rejects_empty_plan():
    with pytest.raises(PlanValidationError, match="no tasks"):
        _validate(_plan(), _KNOWN)
