"""Risk Manager Agent node (AGT-008, PMPT-034/035) — REL-005 Epic E5.4.

Advisory only -- the hardcoded, deterministic risk engine (src/engine/risk/) retains final veto
power (Phase_4_AI_Agent_Design.md §8: "the hardcoded engine has final veto power"). The kill
switch check is the one real, hard gate this node enforces:
`kill_switch_service.is_tripped()`, backed by real DB state
(src/engine/risk/kill_switch_service.py).

REL-016 E16.2 (GLH-08) closed the correlation gap: `^NSEI` (Nifty 50) is now real, ingested
index-level OHLCV data (src/data/ingest/pipeline.py --source yfinance --symbols ^NSEI), and
`_compute_correlation` below converts it plus the candidate's own real backtest equity curve
(`state.equity_curve`, already carried for the Optimization Agent's Monte Carlo re-sampling) into
the two return series `correlation.check_correlation_constraint()` needs. One piece remains
honestly open: this still evaluates the candidate's correlation to Nifty 50 in isolation
(`candidate_weight=1.0`, which algebraically zeroes out whatever `existing_portfolio_returns` is
passed), not blended with a real existing book. UPDATE 2026-08-14: this is no longer a missing-
data-source gap -- REL-034 (2026-08-12) added a real, queryable historical portfolio-equity-curve
table (`AccountEquitySnapshot` / `account_equity_snapshots`, DB-035, src/models/account.py,
`snapshot_date`+`equity` columns, populated daily by
src/engine/paper_trading/equity_snapshot.py::take_daily_snapshot()). `_compute_correlation`
below simply hasn't been updated yet to query it and derive a real `existing_portfolio_returns`
series from it -- the gap is now "not wired," not "no data exists." `correlation_passed` stays
`None` (honestly unavailable, not fabricated) whenever the candidate has no equity curve, the
benchmark data has no overlapping dates, or too few overlapping points exist for a meaningful
correlation.

REL-016 E16.3 (GLH-09) closed the naked-options gap for real: `StrategyLogic.option_legs`
(populated by the Strategy Generator Agent for "F&O" strategies only, prompt v2/PMPT-029) now
gives `naked_options_scanner.scan_for_naked_options()` real, declared legs to check instead of
nothing. `naked_options_checked` stays `False` (not fabricated True) for "Equity" strategies or
any "F&O" strategy the LLM didn't populate legs for.

REL-034 closes the position-sizing gap: `state.account_capital` (the Paper Trading Account's
real live equity, injected by `src/api/routers/agents.py::_execute_graph_run`) is now threaded
through, and `_compute_position_sizing` below calls the real, hardcoded, tested
`position_sizing.compute_position_sizes()` against it. Still honestly `None` (not fabricated)
whenever no Paper account has been seeded yet, or the candidate has no real close-price history
to size against.
"""

import json
from typing import Literal

import pandas as pd
import structlog

from src.agents.llm_router import complete
from src.agents.nodes.common import extract_json
from src.agents.prompt_registry import get_active_prompt
from src.agents.state import (
    EquityCurvePoint,
    RiskAssessment,
    StrategyOptionLeg,
    TradingOSGraphState,
)
from src.core.config import get_settings
from src.data.datalake.query import DataLake
from src.engine.risk import kill_switch_service
from src.engine.risk.correlation import CorrelationCheckResult, check_correlation_constraint
from src.engine.risk.naked_options_scanner import OptionLeg, scan_for_naked_options
from src.engine.risk.position_sizing import compute_position_sizes

PROMPT_SLUG = "risk_manager_agent"
TASK_PROMPT_SLUG = "risk_manager_agent_task"
NOT_COMPUTED_NOTE = "Not checked this pass -- no real data source available (see module docstring)."
BENCHMARK_SYMBOL = "^NSEI"
_MIN_OVERLAPPING_DAYS = 5  # below this, a correlation figure is statistical noise, not a signal
logger = structlog.get_logger(__name__)


def _returns_from_equity_curve(equity_curve: list[EquityCurvePoint]) -> pd.Series:
    dates = [p.date for p in equity_curve]
    equities = [p.equity for p in equity_curve]
    frame = pd.DataFrame({"date": dates, "equity": equities})
    frame["date"] = pd.to_datetime(frame["date"])
    series = frame.set_index("date")["equity"].sort_index().pct_change().dropna()
    return series


def _returns_from_benchmark(symbol: str) -> pd.Series | None:
    data_lake = DataLake(get_settings().data_lake_root / "ohlcv_daily")
    df = data_lake.read_symbol(symbol, None, None)
    if df.is_empty():
        return None
    pdf = df.sort("date").to_pandas().set_index("date")
    pdf.index = pd.to_datetime(pdf.index)
    return pdf["close"].pct_change().dropna()


def _compute_correlation(state: TradingOSGraphState) -> CorrelationCheckResult | None:
    """Returns `None` (not a fabricated result) whenever a real correlation figure can't
    honestly be produced -- see module docstring for exactly which real data source each case
    is missing."""
    if not state.equity_curve:
        return None
    candidate_returns = _returns_from_equity_curve(state.equity_curve)
    benchmark_returns = _returns_from_benchmark(BENCHMARK_SYMBOL)
    if benchmark_returns is None:
        return None

    aligned_candidate, aligned_benchmark = candidate_returns.align(benchmark_returns, join="inner")
    if len(aligned_candidate) < _MIN_OVERLAPPING_DAYS:
        return None

    # candidate_weight=1.0 evaluates the candidate strategy's own correlation to the benchmark in
    # isolation -- algebraically, this zeroes out whatever `existing_portfolio_returns` is passed
    # (see simulate_combined_portfolio_returns), so `aligned_candidate` is passed there too rather
    # than a fabricated "existing portfolio" series. A real source for that series now exists
    # (AccountEquitySnapshot / account_equity_snapshots, DB-035, REL-034) but querying it and
    # blending it in here is still real, open work -- see module docstring's 2026-08-14 update.
    return check_correlation_constraint(
        existing_portfolio_returns=aligned_candidate,
        candidate_returns=aligned_candidate,
        benchmark_returns=aligned_benchmark,
        candidate_weight=1.0,
    )


def _run_naked_options_check(
    declared_legs: list[StrategyOptionLeg] | None,
) -> tuple[bool, list[OptionLeg]]:
    """Returns (checked, naked_legs). `checked=False` (not fabricated True) whenever no legs were
    declared -- an "Equity" strategy, or an "F&O" strategy the LLM didn't populate legs for."""
    if not declared_legs:
        return False, []
    legs = [
        OptionLeg(
            symbol=leg.symbol,
            option_type=leg.option_type,
            strike=leg.strike,
            side=leg.side,
            quantity=leg.quantity,
        )
        for leg in declared_legs
    ]
    result = scan_for_naked_options(legs)
    return True, result.naked_legs


def _compute_position_sizing(state: TradingOSGraphState) -> tuple[str, int | None]:
    """Returns (summary_text, shares). `shares=None` (not fabricated) whenever
    `state.account_capital` is unavailable, the candidate has no real close-price history, or
    the computed size rounds down to zero whole shares at the current price."""
    if state.account_capital is None:
        return NOT_COMPUTED_NOTE, None
    if not state.strategy_logic or not state.strategy_logic.universe:
        return NOT_COMPUTED_NOTE, None
    if len(state.close_curve) < 2:
        return NOT_COMPUTED_NOTE, None

    symbol = state.strategy_logic.universe[0]
    closes = [p.close for p in state.close_curve]
    returns = pd.Series(closes).pct_change().dropna()
    last_price = closes[-1]

    sizes = compute_position_sizes(
        {symbol: returns}, {symbol: last_price}, total_capital=state.account_capital
    )
    result = sizes.get(symbol)
    if result is None or result.shares <= 0:
        return (
            f"Computed a zero-share allocation for {symbol} at the account's current "
            f"₹{state.account_capital:,.2f} equity -- position too small to size at "
            f"₹{last_price:,.2f}/share.",
            None,
        )
    return (
        f"{result.shares} shares of {symbol} (~₹{result.capital_allocation:,.2f}, "
        f"{result.weight:.0%} of the ₹{state.account_capital:,.2f} account equity, "
        "inverse-volatility weighted).",
        result.shares,
    )


def _generate_narrative(
    *,
    hypothesis: str,
    correlation_result: CorrelationCheckResult | None,
    naked_options_checked: bool,
    naked_legs: list[OptionLeg],
    position_sizing_summary: str,
) -> str:
    if correlation_result is None:
        correlation_summary = NOT_COMPUTED_NOTE
    else:
        correlation_summary = (
            f"Candidate-vs-Nifty50 correlation is {correlation_result.correlation:.2f} "
            f"({'within' if correlation_result.passed else 'exceeds'} the "
            f"{correlation_result.limit:.2f} limit)."
        )
    if not naked_options_checked:
        naked_options_summary = NOT_COMPUTED_NOTE
    elif naked_legs:
        naked_options_summary = (
            f"{len(naked_legs)} declared leg(s) have no OTM hedge: "
            + "; ".join(f"{leg.symbol} {leg.option_type} {leg.strike}" for leg in naked_legs)
        )
    else:
        naked_options_summary = "All declared option legs are hedged -- no naked exposure."

    try:
        system_prompt = get_active_prompt(PROMPT_SLUG)
        user_prompt = get_active_prompt(TASK_PROMPT_SLUG).format(
            hypothesis=hypothesis,
            kill_switch_tripped=False,
            correlation_summary=correlation_summary,
            naked_options_summary=naked_options_summary,
            position_sizing_summary=position_sizing_summary,
        )
        response = complete(
            "research",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        parsed = json.loads(extract_json(content))
        return str(parsed["narrative"])
    except Exception as exc:  # noqa: BLE001 - narrative is advisory; never block the loop on it
        logger.warning("risk_manager_narrative_fallback", error=str(exc))
        return (
            f"Kill switch armed (not tripped). Correlation: {correlation_summary} "
            f"Naked-options: {naked_options_summary} Position sizing: {position_sizing_summary}"
        )


def risk_manager_node(state: TradingOSGraphState) -> dict[str, object]:
    if state.optimization_result is None or not state.optimization_result.passed:
        raise ValueError("risk_manager_node requires a passed state.optimization_result")

    if kill_switch_service.is_tripped():
        return {
            "risk_assessment": RiskAssessment(
                decision="Reject",
                kill_switch_tripped=True,
                correlation_passed=None,
                naked_options_checked=False,
                narrative=(
                    "Kill switch is TRIPPED -- the hardcoded Risk Engine has already halted all "
                    "AI deployment loops. No further risk-relevant recommendation is possible "
                    "until a human resets it (API-086)."
                ),
            )
        }

    correlation_result = _compute_correlation(state)
    declared_legs = state.strategy_logic.option_legs if state.strategy_logic else None
    naked_options_checked, naked_legs = _run_naked_options_check(declared_legs)
    position_sizing_summary, position_sizing_shares = _compute_position_sizing(state)

    hypothesis = state.strategy_logic.hypothesis if state.strategy_logic else "unknown strategy"
    narrative = _generate_narrative(
        hypothesis=hypothesis,
        correlation_result=correlation_result,
        naked_options_checked=naked_options_checked,
        naked_legs=naked_legs,
        position_sizing_summary=position_sizing_summary,
    )

    # Advisory decision, deliberately asymmetric between the two checks:
    #   - correlation_ok is STRICT (None does not count as OK). A real graph run always has a
    #     populated state.equity_curve by the time this node runs (Backtesting happens before
    #     Risk in the pipeline) -- an unavailable correlation figure here signals something
    #     upstream is actually missing, not a legitimately-inapplicable check, so it should not
    #     silently pass.
    #   - naked_options_ok is LENIENT (not-checked counts as OK). Naked-options genuinely does
    #     NOT apply to an "Equity" strategy -- that's inapplicability by design, not a gap, the
    #     same non-strict treatment circuit_filter_checked/position_limit_checked already get in
    #     compliance_checker.py for a missing quantity.
    # Either way, the hardcoded Compliance Agent (src/engine/risk/compliance_checker.py) holds
    # the actual veto power over a real naked leg -- this node only narrates and flags.
    correlation_ok = correlation_result is not None and correlation_result.passed
    naked_options_ok = not naked_options_checked or not naked_legs
    decision: Literal["Approve", "ApproveWithRestrictions"] = (
        "Approve" if (correlation_ok and naked_options_ok) else "ApproveWithRestrictions"
    )

    return {
        "risk_assessment": RiskAssessment(
            decision=decision,
            kill_switch_tripped=False,
            correlation_passed=None if correlation_result is None else correlation_result.passed,
            naked_options_checked=naked_options_checked,
            position_sizing_shares=position_sizing_shares,
            narrative=narrative,
        )
    }
