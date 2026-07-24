"""Strategy Factory pipeline (Phase 3 Epic E3.1), per Phase_6_Trading_Engine_Design.md §1:
Code Translation (external -- src/agents/nodes/python_code_generator.py already does this)
-> AST Validation -> Sandbox Execution -> validated .py file + Postgres metadata.

This module owns the second half of that pipeline: given already-generated code, it validates
and -- only on success -- persists a `.py` file to disk and updates the STRATEGY_VERSIONS row's
validation_status in Postgres. Independent of (and reuses the same skills as)
src/agents/nodes/python_validator.py's in-memory LangGraph check, so it can be called from
contexts other than the research graph (e.g. a future re-validation or Phase 4 deployment step).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.agents.tools.registry import get_skill_registry
from src.core.config import get_settings
from src.core.db import get_session
from src.models.strategy import StrategyVersion

STRATEGIES_DIR_NAME = "strategies"


@dataclass(frozen=True)
class StrategyFactoryResult:
    status: Literal["Passed", "Failed"]
    stage_failed: Literal["ast_validation", "sandbox_execution"] | None
    feedback: str | None
    file_path: Path | None


def _strategies_dir() -> Path:
    path = get_settings().data_lake_root.parent / STRATEGIES_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _update_validation_status(
    strategy_version_id: str | None, status: Literal["Passed", "Failed"], feedback: str | None
) -> None:
    if strategy_version_id is None:
        return
    with get_session() as session:
        version = session.get(StrategyVersion, strategy_version_id)
        if version is not None:
            version.validation_status = status
            version.validator_feedback = feedback
            session.commit()


def run_strategy_factory_pipeline(
    code: str, strategy_version_id: str | None = None
) -> StrategyFactoryResult:
    """Runs AST validation then sandbox execution; persists the file + DB status only if both
    pass. `strategy_version_id` is optional so this is directly testable without a DB row --
    when given, it must reference a real STRATEGY_VERSIONS row."""
    registry = get_skill_registry()

    safety = registry.execute("static_safety_check", code=code)
    if not safety["passed"]:
        feedback = "; ".join(safety["violations"])
        _update_validation_status(strategy_version_id, "Failed", feedback)
        return StrategyFactoryResult(
            status="Failed", stage_failed="ast_validation", feedback=feedback, file_path=None
        )

    sandbox = registry.execute("execute_dry_run_sandbox", code=code)
    if not sandbox["passed"]:
        _update_validation_status(strategy_version_id, "Failed", sandbox["error"])
        return StrategyFactoryResult(
            status="Failed",
            stage_failed="sandbox_execution",
            feedback=sandbox["error"],
            file_path=None,
        )

    file_name = f"{strategy_version_id}.py" if strategy_version_id else "unpersisted_strategy.py"
    file_path = _strategies_dir() / file_name
    file_path.write_text(code, encoding="utf-8")
    _update_validation_status(strategy_version_id, "Passed", None)

    return StrategyFactoryResult(
        status="Passed", stage_failed=None, feedback=None, file_path=file_path
    )
