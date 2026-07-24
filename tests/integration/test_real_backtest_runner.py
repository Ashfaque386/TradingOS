"""End-to-end real backtest through the sandbox boundary (Phase 4 Epic E4.3), against the real
year of TCS EOD data ingested in Phase 1 -- the same sandbox src/engine/sandbox/runner.py uses
for Phase 3's validation path, just pointed at real data instead of the synthetic dummy dataset.
Slow (~60-90s): vectorbt's numba JIT compiles cold inside the fresh subprocess every run.
"""

from datetime import date

from src.engine.sandbox.backtest_runner import run_real_backtest

_STRATEGY_CODE = """
import polars as pl
import vectorbt as vbt


def run_backtest(data: pl.DataFrame, config: dict) -> dict:
    close = data["close"].to_pandas()
    close.index = data["date"].to_pandas()
    fast = close.rolling(5).mean()
    slow = close.rolling(20).mean()
    entries = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    exits = (fast < slow) & (fast.shift(1) >= slow.shift(1))
    pf = vbt.Portfolio.from_signals(
        close, entries, exits, init_cash=config.get("init_cash", 100000), freq="1D"
    )

    def clean(x):
        try:
            x = float(x)
            return x if x == x and abs(x) != float("inf") else None
        except Exception:
            return None

    metrics = {
        "sharpe_ratio": clean(pf.sharpe_ratio()),
        "sortino_ratio": clean(pf.sortino_ratio()),
        "calmar_ratio": clean(pf.calmar_ratio()),
        "max_drawdown": clean(pf.max_drawdown()),
        "cagr": clean(pf.annualized_return()),
        "win_rate": clean(pf.trades.win_rate()),
        "profit_factor": clean(pf.trades.profit_factor()),
        "expectancy": clean(pf.trades.expectancy()),
        "total_trades": int(pf.trades.count()),
    }
    equity_curve = [{"date": str(d.date()), "equity": float(v)} for d, v in pf.value().items()]
    return {"metrics": metrics, "equity_curve": equity_curve}
"""


def test_real_backtest_runs_against_real_tcs_data():
    outcome = run_real_backtest(
        _STRATEGY_CODE,
        universe=["TCS"],
        date_from=date(2023, 7, 1),
        date_to=date(2024, 7, 1),
    )

    assert outcome.passed, outcome.error
    assert outcome.symbol_used == "TCS"
    assert outcome.metrics["sharpe_ratio"] is not None
    assert outcome.metrics["max_drawdown"] is not None
    assert outcome.metrics["total_trades"] is not None and outcome.metrics["total_trades"] >= 0
    assert len(outcome.equity_curve) > 200  # a full year of real trading days
    assert outcome.equity_curve[0].equity > 0


def test_real_backtest_reports_missing_data_honestly_not_as_a_crash():
    outcome = run_real_backtest(
        _STRATEGY_CODE,
        universe=["NOT_A_REAL_SYMBOL"],
        date_from=date(2023, 7, 1),
        date_to=date(2024, 7, 1),
    )

    assert not outcome.passed
    assert outcome.error is not None and "no historical data" in outcome.error
    assert outcome.equity_curve == []
