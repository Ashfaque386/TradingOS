"""Real subprocess execution tests -- no mocking, since the sandbox's isolation guarantees are
exactly what's under test."""

from src.engine.sandbox.runner import execute_in_sandbox


def test_sandbox_runs_valid_strategy_successfully():
    code = """
def run_backtest(data, config):
    return {"sharpe_ratio": 1.5, "rows_seen": data.height}
"""
    result = execute_in_sandbox(code, timeout=10.0)
    assert result.passed is True
    assert result.error is None
    assert result.portfolio_summary["sharpe_ratio"] == 1.5
    assert result.portfolio_summary["rows_seen"] > 0


def test_sandbox_reports_missing_run_backtest():
    code = "x = 1\n"
    result = execute_in_sandbox(code, timeout=10.0)
    assert result.passed is False
    assert "run_backtest" in result.error


def test_sandbox_catches_runtime_exception():
    code = """
def run_backtest(data, config):
    raise ValueError("deliberate failure for testing")
"""
    result = execute_in_sandbox(code, timeout=10.0)
    assert result.passed is False
    assert "deliberate failure" in result.error


def test_sandbox_rejects_non_dict_return():
    code = """
def run_backtest(data, config):
    return "not a dict"
"""
    result = execute_in_sandbox(code, timeout=10.0)
    assert result.passed is False
    assert "dict" in result.error


def test_sandbox_blocks_network_access():
    code = """
import socket

def run_backtest(data, config):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(("example.com", 80))
    return {"escaped": True}
"""
    result = execute_in_sandbox(code, timeout=10.0)
    assert result.passed is False
    assert "Network access is disabled" in result.error


def test_sandbox_enforces_cpu_timeout():
    code = """
def run_backtest(data, config):
    total = 0
    while True:
        total += 1
"""
    result = execute_in_sandbox(code, timeout=2.0)
    assert result.passed is False
    assert result.duration_seconds < 10.0  # killed well before it could run forever


def test_sandbox_passes_config_through():
    code = """
def run_backtest(data, config):
    return {"initial_capital": config["initial_capital"]}
"""
    result = execute_in_sandbox(code, config={"initial_capital": 100000}, timeout=10.0)
    assert result.passed is True
    assert result.portfolio_summary["initial_capital"] == 100000
