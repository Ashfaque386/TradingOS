"""Optimization Agent node (AGT-007) — REL-005 Epic E5.3.

Wraps the real Monte Carlo Temporal workflow (src/workers/monte_carlo_workflow.py) -- the first
production caller of this workflow; previously only ever exercised by
tests/integration/test_monte_carlo_workflow.py's own throwaway in-process worker. A real,
standing `monte-carlo-worker` docker-compose service is required for this call to resolve (see
docker-compose.yml) -- without a consumer registered on `settings.temporal_task_queue`, the
`execute_workflow` call below would hang until Temporal's default timeout.

Monte Carlo resamples the strategy's *daily equity-curve returns* (`state.equity_curve`, produced
by the Backtesting Agent), not discrete per-trade P&L -- the sandboxed backtest engine
(src/engine/sandbox/backtest_runner.py) doesn't expose a raw trades ledger, only aggregate
metrics and a daily equity curve. This is a standard, if coarser-grained, resampling input for
this purpose; documented here rather than silently treated as identical to per-trade returns.

Walk-Forward Optimization (src/engine/optimization/walk_forward.py) is now wired in below (REL-024,
2026-08-05), via src/engine/optimization/walk_forward_adapter.py -- the adapter this docstring
used to say was "real, unscoped engineering work ... parked as explicit follow-up work." It uses
`state.entries_exits`/`state.close_curve` (REL-022's real captured signals/prices, threaded onto
state by backtesting_node), not a re-run of the LLM's sandboxed code. Honestly skipped (not
fabricated) when those are empty -- a pre-v3-contract strategy, or a backtest window too short
for even one rolling window; see that adapter module's own docstring for the real numbers.

The Optuna sweep (src/engine/optimization/optuna_sweep.py) is DELIBERATELY STILL NOT invoked
here: it's a separate, unrelated gap from Walk-Forward's (a hyperparameter search over a
strategy's own tunable parameters, which don't exist as a structured concept anywhere in the
LLM-generated code's contract), not addressed by REL-024's adapter or scope. Rather than
fabricate a fake bridge or skip silently, this remaining gap is surfaced honestly in
`OptimizationResult.notes`, matching this codebase's established honestly-stubbed-capability
convention (src/agents/tools/skills.py's SkillNotImplementedError).
"""

import asyncio
from dataclasses import asdict

from temporalio.client import Client

from src.agents.state import EquityCurvePoint, OptimizationResult, TradingOSGraphState
from src.core.config import get_settings
from src.engine.optimization.walk_forward_adapter import run_walk_forward_from_real_backtest
from src.workers.monte_carlo_workflow import (
    MonteCarloWorkflow,
    MonteCarloWorkflowInput,
    MonteCarloWorkflowResult,
)

# Phase_6_Trading_Engine_Design.md §3 establishes P95 max drawdown as the absolute risk metric
# but specifies no numeric pass/fail tolerance for it -- like the Evaluator's Sharpe threshold,
# this multiple is an interim, explicitly documented decision, not a spec-sourced constant.
MAX_ROBUSTNESS_DEGRADATION_MULTIPLE = 1.5

OPTUNA_SKIPPED_NOTE = (
    "Optuna hyperparameter sweep was not run: the LLM-generated strategy code has no structured "
    "tunable-parameter contract to sweep over. Real gap, parked for follow-up -- not fabricated "
    "here."
)


def _equity_curve_returns(equity_curve: list[EquityCurvePoint]) -> list[float]:
    values = [point.equity for point in equity_curve]
    return [
        (curr - prev) / prev for prev, curr in zip(values, values[1:], strict=False) if prev != 0
    ]


def _run_walk_forward(
    state: TradingOSGraphState,
) -> tuple[list[dict[str, object]], bool | None, str]:
    """Returns (results_as_dicts, passed_or_none, a human-readable note) -- `passed` is `None`
    (not `True`/`False`) when WFO didn't run at all, so callers don't conflate "ran and passed
    trivially" with "didn't run"."""
    windows = run_walk_forward_from_real_backtest(
        [(p.date, p.close) for p in state.close_curve],
        [(p.date, p.entry, p.exit) for p in state.entries_exits],
    )
    if not windows:
        return (
            [],
            None,
            "Walk-Forward: skipped -- insufficient real entries/exits or price history for even "
            "one full rolling window (pre-v3-contract strategy, or backtest window shorter than "
            "walk_forward_adapter.py's WALK_FORWARD_TRAIN_PERIOD + WALK_FORWARD_TEST_PERIOD).",
        )
    passed = all(w.out_of_sample_passed for w in windows)
    note = (
        f"Walk-Forward: {len(windows)} rolling out-of-sample windows, "
        f"{'all passed' if passed else 'not all passed'} positive out-of-sample expectancy."
    )
    return ([asdict(w) for w in windows], passed, note)


async def _run_monte_carlo(thread_id: str, trade_returns: list[float]) -> MonteCarloWorkflowResult:
    settings = get_settings()
    client = await Client.connect(settings.temporal_address)
    return await client.execute_workflow(
        MonteCarloWorkflow.run,
        MonteCarloWorkflowInput(trade_returns=trade_returns),
        id=f"monte-carlo-{thread_id}",
        task_queue=settings.temporal_task_queue,
    )


def optimization_node(state: TradingOSGraphState) -> dict[str, object]:
    if state.evaluation_verdict is None or state.evaluation_verdict.verdict != "PASS":
        raise ValueError("optimization_node requires a PASS state.evaluation_verdict")

    # REL-024: independent of the Monte Carlo trade_returns check below -- WFO uses
    # entries_exits/close_curve, not equity_curve, so it can run (or honestly not) regardless of
    # whether there's enough equity-curve data for Monte Carlo re-sampling.
    wf_results, wf_passed, wf_note = _run_walk_forward(state)

    trade_returns = _equity_curve_returns(state.equity_curve)
    if len(trade_returns) < 2:
        return {
            "optimization_result": OptimizationResult(
                passed=False,
                walk_forward_results=wf_results,
                walk_forward_passed=wf_passed,
                notes=f"Insufficient equity curve data for Monte Carlo re-sampling "
                f"({len(trade_returns)} usable daily returns). {wf_note} {OPTUNA_SKIPPED_NOTE}",
            )
        }

    result = asyncio.run(_run_monte_carlo(state.thread_id, trade_returns))

    # `passed` stays scoped to Monte Carlo robustness only (unchanged pipeline gating semantics
    # from before REL-024) -- Walk-Forward's own pass/fail is surfaced separately via
    # `walk_forward_passed`, advisory rather than an additional gate, matching this codebase's
    # existing convention for RiskAssessment (real check, advisory narrative).
    robust = result.percentile_95_max_drawdown <= (
        result.historical_max_drawdown * MAX_ROBUSTNESS_DEGRADATION_MULTIPLE
    )
    notes = (
        f"Monte Carlo P95 max drawdown {result.percentile_95_max_drawdown:.3f} vs. historical "
        f"{result.historical_max_drawdown:.3f} ({'within' if robust else 'exceeds'} "
        f"{MAX_ROBUSTNESS_DEGRADATION_MULTIPLE}x tolerance). {wf_note} {OPTUNA_SKIPPED_NOTE}"
    )
    return {
        "optimization_result": OptimizationResult(
            passed=robust,
            best_params={},
            robustness_score=result.percentile_95_max_drawdown,
            walk_forward_results=wf_results,
            walk_forward_passed=wf_passed,
            notes=notes,
        )
    }
