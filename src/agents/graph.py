"""LangGraph state machine skeleton (Phase 2 Epic E2.1), matching the state diagram in
Phase_3_Low_Level_Design.md §2:

    Research -> Strategy Generator -> Code Gen/Validator loop -> Backtest/Evaluator loop
    -> Optimization -> Risk -> Deployment

Phase 2 implements the graph through the Code_Validation_Loop (CEO/Research, Market Analyst,
Strategy Generator, Python Code Generator, Python Validator -- all real, real LLM calls). The
Backtesting/Evaluator/Optimization/Risk/Deployment agents are Phase 3/4 scope (not built yet),
so a compiled Phase 2 run ends at `await_backtesting`, a placeholder terminal node marking the
state as ready for Phase 3 to pick up -- it does not fabricate a backtest result. Likewise the
Backtest_Loop's escalation rule (5 consecutive strategy rejections -> escalate to CEO) can't be
wired for real until the Evaluator Agent exists; `strategy_rejection_count` is tracked in state
now so that wiring is a small follow-up once Phase 3 lands, not a redesign.
"""

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agents.nodes.ceo import ceo_agent_node
from src.agents.nodes.market_analyst import market_analyst_node
from src.agents.nodes.python_code_generator import python_code_generator_node
from src.agents.nodes.python_validator import python_validator_node
from src.agents.nodes.strategy_generator import strategy_generator_node
from src.agents.state import TradingOSGraphState

MAX_CODE_VALIDATION_RETRIES = 3


def await_backtesting_node(state: TradingOSGraphState) -> dict[str, object]:
    """Placeholder terminal node: validated code is ready, but BacktestingAgent (Phase 3
    Epic E3.x) doesn't exist yet. Returns no state changes -- a real backtest result is never
    fabricated here."""
    return {}


def route_after_validation(state: TradingOSGraphState) -> str:
    if state.validation_result is None:
        raise ValueError("route_after_validation called before python_validator_node ran")
    if state.validation_result.status == "Pass":
        return "await_backtesting"
    if state.code_validation_retry_count >= MAX_CODE_VALIDATION_RETRIES:
        return "END"  # "fail gracefully" per Phase_4 §5 / Phase 2 Epic 1 acceptance criteria
    return "python_code_generator"


def build_graph() -> CompiledStateGraph:  # type: ignore[type-arg]
    graph = StateGraph(TradingOSGraphState)

    graph.add_node("ceo_agent", ceo_agent_node)
    graph.add_node("market_analyst", market_analyst_node)
    graph.add_node("strategy_generator", strategy_generator_node)
    graph.add_node("python_code_generator", python_code_generator_node)
    graph.add_node("python_validator", python_validator_node)
    graph.add_node("await_backtesting", await_backtesting_node)

    graph.set_entry_point("ceo_agent")
    graph.add_edge("ceo_agent", "market_analyst")
    graph.add_edge("market_analyst", "strategy_generator")
    graph.add_edge("strategy_generator", "python_code_generator")
    graph.add_edge("python_code_generator", "python_validator")
    graph.add_conditional_edges(
        "python_validator",
        route_after_validation,
        {
            "await_backtesting": "await_backtesting",
            "python_code_generator": "python_code_generator",
            "END": END,
        },
    )
    graph.add_edge("await_backtesting", END)

    return graph.compile()
