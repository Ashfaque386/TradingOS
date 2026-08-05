from unittest.mock import MagicMock, patch

import pytest

from src.agents.nodes.python_code_generator import python_code_generator_node
from src.agents.state import PythonCode, StrategyLogic, TradingOSGraphState


def _fake_response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices[0].message.content = content
    return response


_STRATEGY = StrategyLogic(
    hypothesis="Mean reversion",
    asset_class="Equity",
    style="Intraday",
    universe=["RELIANCE"],
    entry_conditions="RSI < 30",
    exit_conditions="RSI > 70",
    stop_loss="2%",
    take_profit="4%",
    position_sizing="1% risk",
    confidence_score=0.7,
)


def test_python_code_generator_node_requires_strategy_logic():
    with pytest.raises(ValueError):
        python_code_generator_node(TradingOSGraphState(thread_id="t1"))


def test_python_code_generator_node_strips_fences_and_formats():
    raw_code = "```python\ndef run_backtest(data,config):\n    return {}\n```"
    with (
        patch(
            "src.agents.nodes.python_code_generator.complete", return_value=_fake_response(raw_code)
        ),
        patch("src.agents.nodes.python_code_generator.get_skill_registry") as mock_registry,
    ):
        mock_registry.return_value.execute.side_effect = lambda name, **kw: (
            []
            if name == "search_code_templates"
            else "def run_backtest(data, config):\n    return {}\n"
        )
        state = TradingOSGraphState(thread_id="t1", strategy_logic=_STRATEGY)
        result = python_code_generator_node(state)

    assert result["python_code"].code == "def run_backtest(data, config):\n    return {}\n"
    assert result["python_code"].version_no == 1
    # REL-025: memory_ingest_node's traceability identifier, derived purely from state (no node
    # has a real Postgres StrategyVersion.id to use).
    assert result["strategy_version_id"] == "t1-v1"


def test_python_code_generator_node_increments_version_on_regeneration():
    with (
        patch(
            "src.agents.nodes.python_code_generator.complete",
            return_value=_fake_response("def run_backtest(data, config):\n    return {}\n"),
        ),
        patch("src.agents.nodes.python_code_generator.get_skill_registry") as mock_registry,
    ):
        mock_registry.return_value.execute.side_effect = lambda name, **kw: (
            []
            if name == "search_code_templates"
            else "def run_backtest(data, config):\n    return {}\n"
        )
        state = TradingOSGraphState(
            thread_id="t1",
            strategy_logic=_STRATEGY,
            python_code=PythonCode(code="old", version_no=2),
        )
        result = python_code_generator_node(state)

    assert result["python_code"].version_no == 3
