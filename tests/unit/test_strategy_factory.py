"""Unit tests for the Strategy Factory pipeline, without a strategy_version_id (no DB row
needed -- see tests/integration/test_strategy_factory_persistence.py for the DB-backed path)."""

from src.engine.sandbox.strategy_factory import run_strategy_factory_pipeline


def test_strategy_factory_fails_at_ast_validation_stage():
    result = run_strategy_factory_pipeline("import os\nos.system('ls')")
    assert result.status == "Failed"
    assert result.stage_failed == "ast_validation"
    assert result.file_path is None


def test_strategy_factory_fails_at_sandbox_stage():
    code = "def run_backtest(data, config):\n    raise ValueError('boom')\n"
    result = run_strategy_factory_pipeline(code)
    assert result.status == "Failed"
    assert result.stage_failed == "sandbox_execution"
    assert "boom" in result.feedback
    assert result.file_path is None


def test_strategy_factory_passes_and_persists_file(tmp_path):
    from unittest.mock import patch

    from src.core.config import Settings

    fake_settings = Settings(_env_file=None, data_lake_root=tmp_path / "lake")
    code = "def run_backtest(data, config):\n    return {'sharpe_ratio': 1.2}\n"

    with patch("src.engine.sandbox.strategy_factory.get_settings", return_value=fake_settings):
        result = run_strategy_factory_pipeline(code)

    assert result.status == "Passed"
    assert result.stage_failed is None
    assert result.file_path is not None
    assert result.file_path.exists()
    assert result.file_path.read_text() == code
    assert result.file_path.parent == tmp_path / "strategies"
