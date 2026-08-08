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
  - notify_omni_channel: real Telegram/Discord/Slack outbound dispatch (REL-010 E10.2, Slack
    added REL-027) -- all 3 of FR-10's named platforms now real. WhatsApp was implemented in
    REL-026 and removed at your explicit request (2026-08-07) -- not needed.
  - fetch_india_vix, fetch_nse_sector_data: real Yahoo Finance data (REL-010 E10.3), confirmed
    working tickers, no new vendor/API key.
  - query_news_sentiment: real Qdrant semantic search over the news_sentiment collection
    (REL-010 E10.3).

Honestly-stubbed skills (no live data source wired up yet -- each raises SkillNotImplementedError
rather than fabricating market data): fetch_global_indices, query_macro_calendar. These need a
market-data vendor decision (fetch_global_indices) or a confirmed free structured source
(query_macro_calendar -- no free public RBI policy-calendar feed could be confirmed as of
REL-010 implementation time), not yet made/found as of this docstring's last update.
"""

import ast
import asyncio
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Literal

import black
import yfinance
from qdrant_client import QdrantClient

from src.agents.tools.base import BaseSkill
from src.agents.tools.notifiers import (
    send_discord_followup,
    send_slack_message,
    send_telegram_message,
)
from src.core import vault
from src.core.config import get_settings
from src.core.db import get_session
from src.engine.sandbox.runner import execute_in_sandbox
from src.memory.embeddings import embed_text
from src.models.trading import PortfolioPosition

BANNED_AST_CALLS = {"eval", "exec", "compile", "__import__", "setattr"}
BANNED_IMPORT_MODULES = {"os", "subprocess", "socket", "shutil", "sys", "ctypes"}

# REL-032 (NFR-01): added when src/engine/sandbox/pool.py started reusing a warm sandbox
# subprocess across MULTIPLE strategies' runs (previously every execute_in_sandbox() call got a
# brand-new process, so no strategy's code could ever affect a later, unrelated one). A strategy
# that reassigns an attribute on one of these shared, pre-imported library modules/classes (e.g.
# `vbt.Portfolio.from_signals = something_else`) could otherwise poison every SUBSEQUENT
# strategy's run in the same warm worker until that worker is retired -- a real, new threat this
# pooling change introduces that a fresh-process-per-call model never had. `setattr` is banned
# outright above (a legitimate strategy has no real need for it); this catches the equivalent
# `.`-syntax attribute assignment specifically for the libraries a warm worker keeps imported.
BANNED_ATTRIBUTE_ASSIGNMENT_TARGETS = {
    "vbt",
    "vectorbt",
    "pl",
    "polars",
    "pd",
    "pandas",
    "np",
    "numpy",
    "numba",
}

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


class NewsSentimentQuerySkill(BaseSkill):
    name = "query_news_sentiment"
    description = "Semantic search over real, scored news items in news_sentiment (REL-010 E10.3)."

    def execute(self, *, query: str, top_k: int = 5) -> list[dict[str, Any]]:  # type: ignore[override]
        vector = embed_text(query)
        hits = _qdrant_client().query_points(
            collection_name="news_sentiment", query=vector, limit=top_k
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


def _attribute_root_name(node: ast.expr) -> str | None:
    """Walks an `ast.Attribute` chain (e.g. `vbt.Portfolio.from_signals`) down to its root
    `ast.Name`, or `None` if the chain doesn't bottom out in a plain name (e.g. a function call
    result's attribute, which this check doesn't need to cover -- see REL-032's
    BANNED_ATTRIBUTE_ASSIGNMENT_TARGETS comment for what this is defending against)."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


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
            # REL-032: banned attribute-assignment targets, see BANNED_ATTRIBUTE_ASSIGNMENT_TARGETS'
            # own comment for why this matters now that the real-backtest path reuses a warm
            # sandbox worker across strategies.
            if isinstance(node, ast.Assign | ast.AugAssign):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and _attribute_root_name(target) in BANNED_ATTRIBUTE_ASSIGNMENT_TARGETS
                    ):
                        violations.append(
                            f"banned attribute assignment onto a shared sandbox library at "
                            f"line {node.lineno}"
                        )
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
    description = (
        "Real India VIX close, via the already-integrated yfinance adapter (REL-010 E10.3) -- "
        "no new vendor/API key."
    )
    version = "1.0.0"

    def execute(self, **kwargs: Any) -> Any:
        history = yfinance.Ticker("^INDIAVIX").history(period="5d", interval="1d")
        if history.empty:
            raise SkillNotImplementedError(
                "fetch_india_vix: Yahoo Finance returned no data for ^INDIAVIX"
            )
        last_row = history.iloc[-1]
        return {"date": history.index[-1].date().isoformat(), "close": float(last_row["Close"])}


class NseSectorDataSkill(BaseSkill):
    name = "fetch_nse_sector_data"
    description = (
        "Real NSE sector index closes, via yfinance (REL-010 E10.3) -- confirmed real tickers, "
        "not a full constituent mapping (see _SECTOR_TICKERS)."
    )
    version = "1.0.0"
    # Real, confirmed-working Yahoo Finance tickers for real NSE sector indices (verified
    # empirically at implementation time, not guessed) -- a small, honest subset, not the full
    # NSE sector taxonomy.
    _SECTOR_TICKERS = {
        "IT": "^CNXIT",
        "BANK": "^NSEBANK",
        "AUTO": "^CNXAUTO",
        "PHARMA": "^CNXPHARMA",
    }

    def execute(self, **kwargs: Any) -> Any:
        result: dict[str, Any] = {}
        for sector, ticker in self._SECTOR_TICKERS.items():
            try:
                history = yfinance.Ticker(ticker).history(period="5d", interval="1d")
            except Exception as exc:  # noqa: BLE001 - one bad ticker shouldn't sink the others
                result[sector] = {"error": str(exc)}
                continue
            if history.empty:
                result[sector] = {"error": "no data returned"}
                continue
            result[sector] = {
                "date": history.index[-1].date().isoformat(),
                "close": float(history.iloc[-1]["Close"]),
            }
        if not any("close" in v for v in result.values()):
            raise SkillNotImplementedError(
                "fetch_nse_sector_data: Yahoo Finance returned no data for any sector ticker"
            )
        return result


class MacroCalendarSkill(BaseSkill):
    name = "query_macro_calendar"
    description = "STUB: RBI policy/macro calendar -- no data source wired yet."

    def execute(self, **kwargs: Any) -> Any:
        raise SkillNotImplementedError("query_macro_calendar needs a macro calendar data source")


def _telegram_bot_token() -> str:
    settings = get_settings()
    token = vault.read_bot_token("telegram") or settings.telegram_bot_token
    if not token:
        raise SkillNotImplementedError(
            "notify_omni_channel(channel='telegram') needs a real bot token -- none configured "
            "in Vault or TELEGRAM_BOT_TOKEN"
        )
    return token


def _slack_bot_token() -> str:
    settings = get_settings()
    token = vault.read_bot_token("slack") or settings.slack_bot_token
    if not token:
        raise SkillNotImplementedError(
            "notify_omni_channel(channel='slack') needs a real bot token -- none configured in "
            "Vault or SLACK_BOT_TOKEN"
        )
    return token


class OmniChannelNotifySkill(BaseSkill):
    name = "notify_omni_channel"
    description = "Real outbound Telegram/Discord/Slack dispatch (REL-010 E10.2, REL-027)."
    version = "1.3.0"

    def execute(  # type: ignore[override]
        self,
        *,
        channel: Literal["telegram", "discord", "slack"],
        text: str,
        **kwargs: Any,
    ) -> Any:
        # `SkillNotImplementedError` is reserved for "not configured/not built" only -- a real
        # `httpx.HTTPStatusError` (or, for Slack specifically, `RuntimeError` -- see
        # send_slack_message's own docstring for why) from an actually-attempted send (bot
        # blocked, bad chat_id, ...) is deliberately left to propagate un-wrapped, so a caller
        # distinguishing "this capability doesn't exist" from "it exists and just failed this
        # once" (e.g. src/api/routers/webhooks.py deciding whether to record a real delivery
        # failure) can still tell the two apart, matching every other real skill's honesty
        # convention.
        if channel == "telegram":
            return asyncio.run(
                send_telegram_message(
                    chat_id=kwargs["chat_id"], text=text, bot_token=_telegram_bot_token()
                )
            )
        if channel == "discord":
            application_id = kwargs.get("application_id") or get_settings().discord_application_id
            if not application_id:
                raise SkillNotImplementedError(
                    "notify_omni_channel(channel='discord') needs a real application_id -- none "
                    "provided and DISCORD_APPLICATION_ID is not configured"
                )
            return asyncio.run(
                send_discord_followup(
                    application_id=application_id,
                    interaction_token=kwargs["interaction_token"],
                    content=text,
                )
            )
        # channel == "slack" (REL-027): the Literal type above already narrows this to the only
        # remaining option, so no final else/raise is needed. `channel_id` (the Slack channel to
        # post into) is deliberately not named `channel` in kwargs -- that name is already bound
        # to this method's own platform selector above.
        return asyncio.run(
            send_slack_message(
                channel=kwargs["channel_id"], text=text, bot_token=_slack_bot_token()
            )
        )


ALL_SKILLS: list[BaseSkill] = [
    QdrantStrategyMemorySkill(),
    CodeTemplateSearchSkill(),
    NewsSentimentQuerySkill(),
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
