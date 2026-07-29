"""LangGraph state machine (Phase 2 Epic E2.1 + REL-005 Epic E5), matching the state diagram in
Phase_3_Low_Level_Design.md §2:

    Research -> Strategy Generator -> Code Gen/Validator loop -> Backtest/Evaluator loop
    -> Optimization -> Risk -> Deployment

REL-005 closes the loop that used to terminate at `await_backtesting`, a Phase 2 placeholder --
Backtesting, Evaluator, Optimization, Risk Manager, and Deployment now all run for real. The
Backtest_Loop's escalation rule (5 consecutive strategy rejections -> escalate to CEO) is enforced
below by `route_after_evaluation`: `strategy_generator_node` increments `strategy_rejection_count`
on every FAIL verdict it receives, so by the time this routing function runs after a FAIL, the
count already reflects the prior loop iteration's rejection -- no separate increment happens here.
`ceo_agent_node` resets the counter to 0 on every entry (see its own docstring), so an escalated
re-entry gets a fresh 5-strikes budget rather than immediately re-escalating.
"""

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agents.nodes.backtesting import backtesting_node
from src.agents.nodes.ceo import ceo_agent_node
from src.agents.nodes.compliance import compliance_node
from src.agents.nodes.deployment import deployment_node
from src.agents.nodes.evaluator import evaluator_node
from src.agents.nodes.market_analyst import market_analyst_node
from src.agents.nodes.optimization import optimization_node
from src.agents.nodes.python_code_generator import python_code_generator_node
from src.agents.nodes.python_validator import python_validator_node
from src.agents.nodes.risk_manager import risk_manager_node
from src.agents.nodes.strategy_generator import strategy_generator_node
from src.agents.state import TradingOSGraphState

MAX_CODE_VALIDATION_RETRIES = 3
MAX_REJECTIONS_BEFORE_ESCALATION = 5


def route_after_validation(state: TradingOSGraphState) -> str:
    if state.validation_result is None:
        raise ValueError("route_after_validation called before python_validator_node ran")
    if state.validation_result.status == "Pass":
        return "backtesting"
    if state.code_validation_retry_count >= MAX_CODE_VALIDATION_RETRIES:
        return "END"  # "fail gracefully" per Phase_4 §5 / Phase 2 Epic 1 acceptance criteria
    return "python_code_generator"


def route_after_compliance(state: TradingOSGraphState) -> str:
    if state.compliance_verdict is None:
        raise ValueError("route_after_compliance called before compliance_node ran")
    if state.compliance_verdict.verdict == "Block":
        return "END"
    return "python_validator"


def route_after_evaluation(state: TradingOSGraphState) -> str:
    if state.evaluation_verdict is None:
        raise ValueError("route_after_evaluation called before evaluator_node ran")
    if state.evaluation_verdict.verdict == "PASS":
        return "optimization"
    if state.strategy_rejection_count >= MAX_REJECTIONS_BEFORE_ESCALATION:
        return "ceo_agent"  # escalate: loosen constraints per Phase_4 §11/§3
    return "strategy_generator"


def build_graph() -> CompiledStateGraph:  # type: ignore[type-arg]
    graph = StateGraph(TradingOSGraphState)

    graph.add_node("ceo_agent", ceo_agent_node)
    graph.add_node("market_analyst", market_analyst_node)
    graph.add_node("strategy_generator", strategy_generator_node)
    graph.add_node("python_code_generator", python_code_generator_node)
    graph.add_node("compliance", compliance_node)
    graph.add_node("python_validator", python_validator_node)
    graph.add_node("backtesting", backtesting_node)
    graph.add_node("evaluator", evaluator_node)
    graph.add_node("optimization", optimization_node)
    graph.add_node("risk_manager", risk_manager_node)
    graph.add_node("deployment", deployment_node)

    graph.set_entry_point("ceo_agent")
    graph.add_edge("ceo_agent", "market_analyst")
    graph.add_edge("market_analyst", "strategy_generator")
    graph.add_edge("strategy_generator", "python_code_generator")
    graph.add_edge("python_code_generator", "compliance")
    graph.add_conditional_edges(
        "compliance",
        route_after_compliance,
        {"python_validator": "python_validator", "END": END},
    )
    graph.add_conditional_edges(
        "python_validator",
        route_after_validation,
        {
            "backtesting": "backtesting",
            "python_code_generator": "python_code_generator",
            "END": END,
        },
    )
    graph.add_edge("backtesting", "evaluator")
    graph.add_conditional_edges(
        "evaluator",
        route_after_evaluation,
        {
            "optimization": "optimization",
            "strategy_generator": "strategy_generator",
            "ceo_agent": "ceo_agent",
        },
    )
    graph.add_edge("optimization", "risk_manager")
    graph.add_edge("risk_manager", "deployment")
    graph.add_edge("deployment", END)

    return graph.compile()
