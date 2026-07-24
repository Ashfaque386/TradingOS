from unittest.mock import patch

import pytest

from src.agents.nodes.python_validator import python_validator_node
from src.agents.state import PythonCode, TradingOSGraphState


def _mock_skills(*, safety=None, lint=None, sandbox=None):
    safety = safety or {"passed": True, "violations": []}
    lint = lint or {"passed": True, "findings": ""}
    sandbox = sandbox or {"passed": True, "error": None}

    def side_effect(name, **kwargs):
        return {
            "static_safety_check": safety,
            "run_linter": lint,
            "execute_dry_run_sandbox": sandbox,
        }[name]

    return side_effect


def test_python_validator_node_requires_python_code():
    with pytest.raises(ValueError):
        python_validator_node(TradingOSGraphState(thread_id="t1"))


def test_python_validator_node_passes_clean_code():
    state = TradingOSGraphState(
        thread_id="t1", python_code=PythonCode(code="def run_backtest(): return {}")
    )
    with patch("src.agents.nodes.python_validator.get_skill_registry") as mock_registry:
        mock_registry.return_value.execute.side_effect = _mock_skills()
        result = python_validator_node(state)

    assert result["validation_result"].status == "Pass"
    assert result["code_validation_retry_count"] == 0


def test_python_validator_node_fails_and_increments_retry_count():
    state = TradingOSGraphState(
        thread_id="t1",
        python_code=PythonCode(code="eval('bad')"),
        code_validation_retry_count=1,
    )
    with patch("src.agents.nodes.python_validator.get_skill_registry") as mock_registry:
        mock_registry.return_value.execute.side_effect = _mock_skills(
            safety={"passed": False, "violations": ["banned call: eval()"]}
        )
        result = python_validator_node(state)

    assert result["validation_result"].status == "Fail"
    assert result["validation_result"].severity == "Critical"
    assert result["code_validation_retry_count"] == 2


def test_python_validator_node_skips_sandbox_when_safety_check_fails():
    """No reason to execute code we've already proven is unsafe."""
    state = TradingOSGraphState(thread_id="t1", python_code=PythonCode(code="eval('bad')"))
    with patch("src.agents.nodes.python_validator.get_skill_registry") as mock_registry:
        mock_registry.return_value.execute.side_effect = _mock_skills(
            safety={"passed": False, "violations": ["banned call: eval()"]}
        )
        python_validator_node(state)

    called_skills = [call.args[0] for call in mock_registry.return_value.execute.call_args_list]
    assert called_skills == ["static_safety_check"]


def test_python_validator_node_fails_on_lint_findings_alone():
    state = TradingOSGraphState(thread_id="t1", python_code=PythonCode(code="import json\n"))
    with patch("src.agents.nodes.python_validator.get_skill_registry") as mock_registry:
        mock_registry.return_value.execute.side_effect = _mock_skills(
            lint={"passed": False, "findings": "F401 unused import"}
        )
        result = python_validator_node(state)

    assert result["validation_result"].status == "Fail"
    assert result["validation_result"].severity == "Medium"


def test_python_validator_node_fails_on_sandbox_error_alone():
    state = TradingOSGraphState(
        thread_id="t1", python_code=PythonCode(code="def run_backtest(): 1/0")
    )
    with patch("src.agents.nodes.python_validator.get_skill_registry") as mock_registry:
        mock_registry.return_value.execute.side_effect = _mock_skills(
            sandbox={"passed": False, "error": "ZeroDivisionError: division by zero"}
        )
        result = python_validator_node(state)

    assert result["validation_result"].status == "Fail"
    assert "ZeroDivisionError" in result["validation_result"].feedback
