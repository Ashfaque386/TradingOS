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

Walk-Forward Optimization and the Optuna sweep (src/engine/optimization/walk_forward.py,
optuna_sweep.py) are DELIBERATELY NOT invoked here: both require a `StrategyFn` callable
(`close: pd.Series -> (entries: pd.Series, exits: pd.Series)`), a vectorized-signal contract with
no adapter from the LLM-generated sandboxed strategy code this graph actually produces (which
implements `run_backtest(data, config) -> {"metrics":..., "equity_curve":...}` per the PMPT-004
v2 prompt -- an entirely different, incompatible representation). Building that adapter is real,
unscoped engineering work discovered during REL-005 implementation, not a wiring task; rather
than fabricate a fake bridge or skip silently, this gap is surfaced honestly in
`OptimizationResult.notes` and parked as explicit follow-up work, matching this codebase's
established honestly-stubbed-capability convention (src/agents/tools/skills.py's
SkillNotImplementedError).
"""

import asyncio

from temporalio.client import Client

from src.agents.state import EquityCurvePoint, OptimizationResult, TradingOSGraphState
from src.core.config import get_settings
from src.workers.monte_carlo_workflow import (
    MonteCarloWorkflow,
    MonteCarloWorkflowInput,
    MonteCarloWorkflowResult,
)

# Phase_6_Trading_Engine_Design.md §3 establishes P95 max drawdown as the absolute risk metric
# but specifies no numeric pass/fail tolerance for it -- like the Evaluator's Sharpe threshold,
# this multiple is an interim, explicitly documented decision, not a spec-sourced constant.
MAX_ROBUSTNESS_DEGRADATION_MULTIPLE = 1.5

WFO_OPTUNA_SKIPPED_NOTE = (
    "Walk-Forward Optimization and the Optuna sweep were not run: both require a vectorized "
    "close->(entries,exits) StrategyFn, and no adapter exists from the LLM-generated sandboxed "
    "strategy code (run_backtest(data, config) contract) to that representation. Real gap, "
    "parked for follow-up -- not fabricated here."
)


def _equity_curve_returns(equity_curve: list[EquityCurvePoint]) -> list[float]:
    values = [point.equity for point in equity_curve]
    return [
        (curr - prev) / prev for prev, curr in zip(values, values[1:], strict=False) if prev != 0
    ]


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

    trade_returns = _equity_curve_returns(state.equity_curve)
    if len(trade_returns) < 2:
        return {
            "optimization_result": OptimizationResult(
                passed=False,
                notes=f"Insufficient equity curve data for Monte Carlo re-sampling "
                f"({len(trade_returns)} usable daily returns). {WFO_OPTUNA_SKIPPED_NOTE}",
            )
        }

    result = asyncio.run(_run_monte_carlo(state.thread_id, trade_returns))

    robust = result.percentile_95_max_drawdown <= (
        result.historical_max_drawdown * MAX_ROBUSTNESS_DEGRADATION_MULTIPLE
    )
    notes = (
        f"Monte Carlo P95 max drawdown {result.percentile_95_max_drawdown:.3f} vs. historical "
        f"{result.historical_max_drawdown:.3f} ({'within' if robust else 'exceeds'} "
        f"{MAX_ROBUSTNESS_DEGRADATION_MULTIPLE}x tolerance). {WFO_OPTUNA_SKIPPED_NOTE}"
    )
    return {
        "optimization_result": OptimizationResult(
            passed=robust,
            best_params={},
            robustness_score=result.percentile_95_max_drawdown,
            notes=notes,
        )
    }
