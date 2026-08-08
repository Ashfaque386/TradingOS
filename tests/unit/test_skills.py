import pytest

from src.agents.tools.skills import (
    FormatPythonCodeSkill,
    GlobalIndicesSkill,
    RunLinterSkill,
    SkillNotImplementedError,
    StaticSafetyCheckSkill,
)


def test_format_python_code_normalizes_style():
    skill = FormatPythonCodeSkill()
    result = skill.execute(code="def f(x,y):\n    return x+y\n")
    assert result == "def f(x, y):\n    return x + y\n"


def test_format_python_code_rejects_invalid_syntax():
    skill = FormatPythonCodeSkill()
    with pytest.raises(ValueError):
        skill.execute(code="def f(x, y):\n    return x +")


def test_run_linter_passes_clean_code():
    skill = RunLinterSkill()
    result = skill.execute(code="def f(x: int) -> int:\n    return x + 1\n")
    assert result["passed"] is True


def test_run_linter_flags_unused_import():
    skill = RunLinterSkill()
    result = skill.execute(code="import os\n\ndef f() -> int:\n    return 1\n")
    assert result["passed"] is False
    assert "F401" in result["findings"] or "os" in result["findings"]


def test_static_safety_check_flags_eval():
    skill = StaticSafetyCheckSkill()
    result = skill.execute(code="eval('1+1')")
    assert result["passed"] is False
    assert any("eval" in v for v in result["violations"])


def test_static_safety_check_flags_banned_import():
    skill = StaticSafetyCheckSkill()
    result = skill.execute(code="import os\nos.system('ls')")
    assert result["passed"] is False
    assert any("os" in v for v in result["violations"])


def test_static_safety_check_passes_clean_strategy_code():
    skill = StaticSafetyCheckSkill()
    code = """
import polars as pl

def run_backtest(data: pl.DataFrame, config: dict) -> dict:
    return {"sharpe": 1.5}
"""
    result = skill.execute(code=code)
    assert result["passed"] is True
    assert result["violations"] == []


def test_static_safety_check_flags_syntax_error():
    skill = StaticSafetyCheckSkill()
    result = skill.execute(code="def f(:\n    pass")
    assert result["passed"] is False


def test_static_safety_check_flags_negative_shift_look_ahead_bias():
    skill = StaticSafetyCheckSkill()
    code = "signal = df['close'].shift(-1) > df['close']"
    result = skill.execute(code=code)
    assert result["passed"] is False
    assert any("look-ahead" in v for v in result["violations"])


def test_static_safety_check_allows_positive_shift():
    skill = StaticSafetyCheckSkill()
    code = "prev_close = df['close'].shift(1)"
    result = skill.execute(code=code)
    assert result["passed"] is True


def test_static_safety_check_flags_setattr():
    """REL-032: setattr is banned outright now that the real-backtest path reuses a warm
    sandbox worker across strategies (src/engine/sandbox/pool.py) -- a legitimate strategy has
    no real need for it."""
    skill = StaticSafetyCheckSkill()
    result = skill.execute(code="setattr(some_obj, 'x', 1)")
    assert result["passed"] is False
    assert any("setattr" in v for v in result["violations"])


@pytest.mark.parametrize(
    "code",
    [
        "vbt.Portfolio.from_signals = lambda *a, **kw: None",
        "vectorbt.something = 1",
        "pl.DataFrame = None",
        "np.array = None",
        "numba.njit = None",
    ],
)
def test_static_safety_check_flags_attribute_assignment_onto_shared_sandbox_libraries(code):
    """REL-032: a strategy that reassigns an attribute on a shared, pre-imported pool library
    could otherwise poison every SUBSEQUENT strategy's run in the same warm worker -- a real,
    new threat pooling introduces that a fresh-process-per-call model never had."""
    skill = StaticSafetyCheckSkill()
    result = skill.execute(code=code)
    assert result["passed"] is False
    assert any("banned attribute assignment" in v for v in result["violations"])


def test_static_safety_check_allows_attribute_assignment_onto_a_strategys_own_object():
    """Only the specific shared sandbox-library aliases are banned -- a strategy assigning
    attributes on its own local objects (e.g. inside a class it defines) is unaffected."""
    skill = StaticSafetyCheckSkill()
    code = """
class MyStrategy:
    def __init__(self):
        self.position = 0

s = MyStrategy()
s.position = 10
"""
    result = skill.execute(code=code)
    assert result["passed"] is True


def test_stub_skills_raise_not_implemented_rather_than_fabricate_data():
    with pytest.raises(SkillNotImplementedError):
        GlobalIndicesSkill().execute()
