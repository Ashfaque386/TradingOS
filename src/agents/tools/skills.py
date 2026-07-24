"""Concrete Skill implementations for the Phase 2 E2.3 agent workforce.

Real, working skills (backed by infrastructure that already exists from Phase 1/2/3):
  - query_qdrant_strategy_memory, search_code_templates: real Qdrant semantic search.
  - format_python_code: real `black` formatting.
  - run_linter: real `ruff check` over a code string.
  - static_safety_check: real AST-based ban list (look-ahead/naked-exec patterns).
  - execute_dry_run_sandbox: real subprocess sandbox execution (Phase 3 Epic E3.1,
    src/engine/sandbox/runner.py) -- the full dry-run named in Phase_4_AI_Agent_Design.md's
    Python Validator Agent spec, now real rather than a stand-in.
  - fetch_portfolio_status: real query against the PORTFOLIO_POSITIONS table.

Honestly-stubbed skills (no live data source wired up yet -- each raises SkillNotImplementedError
rather than fabricating market data): fetch_global_indices, fetch_india_vix,
fetch_nse_sector_data, query_macro_calendar, notify_omni_channel. These need either a market-data
vendor decision or the Phase 4 omni-channel webhook gateway, neither built yet.
"""

import ast
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import black
from qdrant_client import QdrantClient

from src.agents.tools.base import BaseSkill
from src.core.config import get_settings
from src.core.db import get_session
from src.engine.sandbox.runner import execute_in_sandbox
from src.memory.embeddings import embed_text
from src.models.trading import PortfolioPosition

BANNED_AST_CALLS = {"eval", "exec", "compile", "__import__"}
BANNED_IMPORT_MODULES = {"os", "subprocess", "socket", "shutil", "sys", "ctypes"}

# Attribute-style calls (e.g. `os.system(...)`) flagged regardless of whether the matching
# `import os` statement is present in the SAME snippet -- catches the intent even when an
# attacker relies on `os` being reachable some other way (a builtin injected elsewhere, a
# `from os import system as x` alias, etc.), rather than only catching the literal import line.
BANNED_ATTRIBUTE_CALLS: dict[str, set[str]] = {
    "os": {"system", "popen", "execv", "execve", "execvp", "spawnv", "spawnve", "remove", "unlink"},
    "subprocess": {"run", "call", "Popen", "check_output", "check_call"},
    "shutil": {"rmtree", "move"},
    "socket": {"socket", "create_connection"},
}


class SkillNotImplementedError(RuntimeError):
    """Raised by honestly-stubbed skills -- no fabricated data is ever returned."""


def _qdrant_client() -> QdrantClient:
    return QdrantClient(url=get_settings().qdrant_url)


class QdrantStrategyMemorySkill(BaseSkill):
    name = "query_qdrant_strategy_memory"
    description = "Semantic search over past strategy outcomes in trading_strategies."

    def execute(self, *, query: str, top_k: int = 5) -> list[dict[str, Any]]:  # type: ignore[override]
        vector = embed_text(query)
        hits = _qdrant_client().query_points(
            collection_name="trading_strategies", query=vector, limit=top_k
        )
        return [{"score": h.score, "payload": h.payload} for h in hits.points]


class CodeTemplateSearchSkill(BaseSkill):
    name = "search_code_templates"
    description = "Semantic search over the Golden Code Template library in Qdrant."

    def execute(self, *, query: str, top_k: int = 5) -> list[dict[str, Any]]:  # type: ignore[override]
        vector = embed_text(query)
        hits = _qdrant_client().query_points(
            collection_name="code_templates", query=vector, limit=top_k
        )
        return [{"score": h.score, "payload": h.payload} for h in hits.points]


class FormatPythonCodeSkill(BaseSkill):
    name = "format_python_code"
    description = "Formats a Python source string with black."

    def execute(self, *, code: str) -> str:  # type: ignore[override]
        try:
            return black.format_str(code, mode=black.Mode(line_length=100))
        except black.InvalidInput as exc:  # type: ignore[attr-defined]
            raise ValueError(f"code could not be formatted (syntax error): {exc}") from exc


class RunLinterSkill(BaseSkill):
    name = "run_linter"
    description = "Runs ruff check over a Python source string; returns (passed, findings)."

    def execute(self, *, code: str) -> dict[str, Any]:  # type: ignore[override]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            temp_path = Path(f.name)
        try:
            result = subprocess.run(
                ["ruff", "check", "--output-format=concise", str(temp_path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
        finally:
            temp_path.unlink(missing_ok=True)
        return {"passed": result.returncode == 0, "findings": result.stdout.strip()}


def _is_negative_number(node: ast.expr) -> bool:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return isinstance(node.operand, ast.Constant) and isinstance(
            node.operand.value, (int, float)
        )
    return (
        isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and node.value < 0
    )


class StaticSafetyCheckSkill(BaseSkill):
    name = "static_safety_check"
    description = "AST-based static safety scan (banned calls/imports/look-ahead bias)."

    def execute(self, *, code: str) -> dict[str, Any]:  # type: ignore[override]
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return {"passed": False, "violations": [f"SyntaxError: {exc}"]}

        violations: list[str] = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in BANNED_AST_CALLS
            ):
                violations.append(f"banned call: {node.func.id}() at line {node.lineno}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in BANNED_IMPORT_MODULES:
                        violations.append(f"banned import: {alias.name} at line {node.lineno}")
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.split(".")[0] in BANNED_IMPORT_MODULES
            ):
                violations.append(f"banned import: {node.module} at line {node.lineno}")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.attr in BANNED_ATTRIBUTE_CALLS.get(node.func.value.id, set())
            ):
                violations.append(
                    f"banned call: {node.func.value.id}.{node.func.attr}() at line {node.lineno}"
                )
            # Look-ahead bias heuristic: `.shift(-N)` (N > 0) pulls a FUTURE row's value into
            # the current row in both Polars and pandas -- a classic bug when used to compute
            # a trading signal, since real-time execution can never see tomorrow's price.
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "shift"
                and node.args
                and _is_negative_number(node.args[0])
            ):
                violations.append(
                    f"possible look-ahead bias: negative .shift() at line {node.lineno} "
                    "pulls future data into the current row"
                )

        return {"passed": len(violations) == 0, "violations": violations}


class ExecuteDryRunSandboxSkill(BaseSkill):
    name = "execute_dry_run_sandbox"
    description = (
        "Runs the strategy's run_backtest() in an isolated subprocess against a dummy "
        "dataset (Phase 3 Epic E3.1, src/engine/sandbox/runner.py)."
    )

    def execute(self, *, code: str, timeout: float = 10.0) -> dict[str, Any]:  # type: ignore[override]
        result = execute_in_sandbox(code, timeout=timeout)
        return {
            "passed": result.passed,
            "error": result.error,
            "portfolio_summary": result.portfolio_summary,
            "duration_seconds": result.duration_seconds,
        }


class PortfolioStatusSkill(BaseSkill):
    name = "fetch_portfolio_status"
    description = "Reads current net positions/PnL for an account from PORTFOLIO_POSITIONS."

    def execute(self, *, account_id: str) -> list[dict[str, Any]]:  # type: ignore[override]
        with get_session() as session:
            rows = (
                session.query(PortfolioPosition)
                .filter(PortfolioPosition.account_id == account_id)
                .all()
            )
            return [
                {
                    "symbol": r.symbol,
                    "net_quantity": r.net_quantity,
                    "avg_price": float(r.avg_price) if r.avg_price is not None else None,
                    "unrealized_pnl": float(r.unrealized_pnl),
                    "realized_pnl": float(r.realized_pnl),
                }
                for r in rows
            ]


class GlobalIndicesSkill(BaseSkill):
    name = "fetch_global_indices"
    description = "STUB: SGX Nifty / NASDAQ overnight cues -- no market-data vendor wired yet."

    def execute(self, **kwargs: Any) -> Any:
        raise SkillNotImplementedError(
            "fetch_global_indices needs a global-indices data vendor decision (not yet made)"
        )


class IndiaVixSkill(BaseSkill):
    name = "fetch_india_vix"
    description = "STUB: India VIX -- no market-data vendor wired yet."

    def execute(self, **kwargs: Any) -> Any:
        raise SkillNotImplementedError("fetch_india_vix needs a live NSE VIX data source")


class NseSectorDataSkill(BaseSkill):
    name = "fetch_nse_sector_data"
    description = "STUB: NSE sector rotation/internals -- no sector-index mapping ingested yet."

    def execute(self, **kwargs: Any) -> Any:
        raise SkillNotImplementedError(
            "fetch_nse_sector_data needs a sector-constituent mapping not yet ingested "
            "(only raw per-symbol OHLCV exists from Phase 1)"
        )


class MacroCalendarSkill(BaseSkill):
    name = "query_macro_calendar"
    description = "STUB: RBI policy/macro calendar -- no data source wired yet."

    def execute(self, **kwargs: Any) -> Any:
        raise SkillNotImplementedError("query_macro_calendar needs a macro calendar data source")


class OmniChannelNotifySkill(BaseSkill):
    name = "notify_omni_channel"
    description = "STUB: Telegram/Discord/WhatsApp/Slack notify -- gateway is Phase 4 scope."

    def execute(self, **kwargs: Any) -> Any:
        raise SkillNotImplementedError(
            "notify_omni_channel needs the omni-channel webhook gateway (Phase 4, LLD §9.2)"
        )


ALL_SKILLS: list[BaseSkill] = [
    QdrantStrategyMemorySkill(),
    CodeTemplateSearchSkill(),
    FormatPythonCodeSkill(),
    RunLinterSkill(),
    StaticSafetyCheckSkill(),
    ExecuteDryRunSandboxSkill(),
    PortfolioStatusSkill(),
    GlobalIndicesSkill(),
    IndiaVixSkill(),
    NseSectorDataSkill(),
    MacroCalendarSkill(),
    OmniChannelNotifySkill(),
]
