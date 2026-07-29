"""REL-008 E8.6: two small, independent training graphs, deliberately separate from
src/agents/graph.py's main 11-node strategy-generation graph.

Model training/evaluation is not part of every strategy-generation run, and the main graph is
fully tested and working -- adding unrelated nodes/conditional edges to it would be pure blast
radius for no benefit. Both graphs share the same `model_evaluator_node` and
`TradingOSGraphState` type, so any future orchestration/streaming code that already knows how to
walk a `CompiledStateGraph` over that state type works unchanged against these too.
"""

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agents.nodes.ml_agent import ml_agent_node
from src.agents.nodes.model_evaluator import model_evaluator_node
from src.agents.nodes.rl_agent import rl_agent_node
from src.agents.state import TradingOSGraphState


def build_supervised_training_graph() -> CompiledStateGraph:  # type: ignore[type-arg]
    graph = StateGraph(TradingOSGraphState)
    graph.add_node("ml_agent", ml_agent_node)
    graph.add_node("model_evaluator", model_evaluator_node)
    graph.set_entry_point("ml_agent")
    graph.add_edge("ml_agent", "model_evaluator")
    graph.add_edge("model_evaluator", END)
    return graph.compile()


def build_rl_training_graph() -> CompiledStateGraph:  # type: ignore[type-arg]
    graph = StateGraph(TradingOSGraphState)
    graph.add_node("rl_agent", rl_agent_node)
    graph.add_node("model_evaluator", model_evaluator_node)
    graph.set_entry_point("rl_agent")
    graph.add_edge("rl_agent", "model_evaluator")
    graph.add_edge("model_evaluator", END)
    return graph.compile()
