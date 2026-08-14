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

UPDATE 2026-08-14 (REL-053): the Optuna sweep (src/engine/optimization/optuna_sweep.py) is now
wired in for real, via the new src/engine/optimization/optuna_strategy_adapter.py -- but only
per-strategy, when `state.strategy_logic.tunable_parameters` is declared (a new structured
parameter-space contract the Strategy Generator Agent may optionally emit, see StrategyLogic's
own docstring). Unlike Walk-Forward's adapter, which replays one already-captured real signal
series, Optuna's adapter must RE-EXECUTE the real sandbox once per trial (each trial's parameters
genuinely change the generated code's behavior) -- a real, non-trivial per-trial cost, which is
why `_OPTUNA_N_TRIALS` below is tuned down from `run_optuna_sweep`'s own library default of 50.
`optuna_ran` stays honestly `False` (not fabricated) whenever no `tunable_parameters` were
declared for this strategy, matching this codebase's established honestly-stubbed-capability
convention (src/agents/tools/skills.py's SkillNotImplementedError) for the (still common, for
now) case where a strategy declares nothing to sweep over.
"""

import asyncio
from dataclasses import asdict
from datetime import date

import pandas as pd
from temporalio.client import Client

from src.agents.state import EquityCurvePoint, OptimizationResult, TradingOSGraphState
from src.core.config import get_settings
from src.engine.optimization.optuna_strategy_adapter import sandboxed_code_to_strategy_factory
from src.engine.optimization.optuna_sweep import OptunaSweepResult, run_optuna_sweep
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
    "tunable-parameter contract declared for this strategy. Not every strategy needs one -- see "
    "OptimizationResult.optuna_ran."
)
OPTUNA_MISSING_PREREQS_NOTE = (
    "Optuna hyperparameter sweep was not run: tunable_parameters were declared, but "
    "python_code/close_curve/universe are not all available yet to build a real sweep from. "
    "Real gap, not fabricated here."
)
# Each trial re-executes the real sandbox (see optuna_strategy_adapter.py's own docstring:
# ~9-29s cold / ~0.06s warm per call) -- tuned down from run_optuna_sweep()'s own library default
# of 50 to keep a real strategy-generation run's total latency bounded.
_OPTUNA_N_TRIALS = 15


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


def _run_optuna_sweep(state: TradingOSGraphState) -> tuple[OptunaSweepResult | None, str]:
    """Returns (result, note). `result=None` (not fabricated) whenever this strategy declared no
    `tunable_parameters`, or the real data needed to build a sweep (python_code/close_curve/
    universe) isn't available -- two different honest reasons, two different notes."""
    if not state.strategy_logic or not state.strategy_logic.tunable_parameters:
        return None, OPTUNA_SKIPPED_NOTE
    if not state.python_code or not state.close_curve or not state.strategy_logic.universe:
        return None, OPTUNA_MISSING_PREREQS_NOTE

    dates = [p.date for p in state.close_curve]
    close = pd.Series(
        [p.close for p in state.close_curve], index=pd.to_datetime(dates)
    ).sort_index()
    factory = sandboxed_code_to_strategy_factory(
        state.python_code.code,
        universe=state.strategy_logic.universe,
        date_from=date.fromisoformat(min(dates)),
        date_to=date.fromisoformat(max(dates)),
    )
    # Deterministic per-thread seed (not per-run-random) so a re-run against the same candidate
    # reproduces the same sweep, matching run_optuna_sweep()'s own seed-for-determinism contract.
    seed = abs(hash(state.thread_id)) % (2**32)
    result = run_optuna_sweep(
        close,
        state.strategy_logic.tunable_parameters,
        factory,
        n_trials=_OPTUNA_N_TRIALS,
        seed=seed,
    )
    note = (
        f"Optuna: {_OPTUNA_N_TRIALS} trials, best sharpe_ratio={result.best_value:.3f}, "
        f"params={result.best_params}."
    )
    return result, note


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

    # REL-024/REL-053: both independent of the Monte Carlo trade_returns check below -- WFO uses
    # entries_exits/close_curve and Optuna uses close_curve/python_code/tunable_parameters, not
    # equity_curve, so both can run (or honestly not) regardless of whether there's enough
    # equity-curve data for Monte Carlo re-sampling.
    wf_results, wf_passed, wf_note = _run_walk_forward(state)
    optuna_result, optuna_note = _run_optuna_sweep(state)

    trade_returns = _equity_curve_returns(state.equity_curve)
    if len(trade_returns) < 2:
        return {
            "optimization_result": OptimizationResult(
                passed=False,
                best_params=optuna_result.best_params if optuna_result else {},
                walk_forward_results=wf_results,
                walk_forward_passed=wf_passed,
                optuna_ran=optuna_result is not None,
                optuna_best_value=optuna_result.best_value if optuna_result else None,
                optuna_parameter_importances=(
                    optuna_result.parameter_importances if optuna_result else {}
                ),
                notes=f"Insufficient equity curve data for Monte Carlo re-sampling "
                f"({len(trade_returns)} usable daily returns). {wf_note} {optuna_note}",
            )
        }

    result = asyncio.run(_run_monte_carlo(state.thread_id, trade_returns))

    # `passed` stays scoped to Monte Carlo robustness only (unchanged pipeline gating semantics
    # from before REL-024) -- Walk-Forward's and Optuna's own results are surfaced separately,
    # advisory rather than an additional gate, matching this codebase's existing convention for
    # RiskAssessment (real check, advisory narrative).
    robust = result.percentile_95_max_drawdown <= (
        result.historical_max_drawdown * MAX_ROBUSTNESS_DEGRADATION_MULTIPLE
    )
    notes = (
        f"Monte Carlo P95 max drawdown {result.percentile_95_max_drawdown:.3f} vs. historical "
        f"{result.historical_max_drawdown:.3f} ({'within' if robust else 'exceeds'} "
        f"{MAX_ROBUSTNESS_DEGRADATION_MULTIPLE}x tolerance). {wf_note} {optuna_note}"
    )
    return {
        "optimization_result": OptimizationResult(
            passed=robust,
            best_params=optuna_result.best_params if optuna_result else {},
            robustness_score=result.percentile_95_max_drawdown,
            walk_forward_results=wf_results,
            walk_forward_passed=wf_passed,
            optuna_ran=optuna_result is not None,
            optuna_best_value=optuna_result.best_value if optuna_result else None,
            optuna_parameter_importances=(
                optuna_result.parameter_importances if optuna_result else {}
            ),
            notes=notes,
        )
    }
