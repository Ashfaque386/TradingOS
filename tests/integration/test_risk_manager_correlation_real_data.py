"""REL-016 E16.2 (GLH-08) integration test, against the REAL ingested `^NSEI` (Nifty 50) Parquet
data in the data lake (ingested via `python -m src.data.ingest.pipeline --source yfinance
--symbols ^NSEI --start 2023-07-21 --end 2024-07-19`) -- no mocking of the benchmark series
itself, matching this codebase's convention of testing real local infrastructure directly.

A candidate's own equity curve is synthetic here (there's no real historical strategy backtest
handy to reuse), but is deliberately built to either closely TRACK or be roughly UNCORRELATED
with the real Nifty 50 daily returns pulled from the data lake for the exact same real dates --
so the correlation figure itself is computed for real from a real benchmark series, only the
candidate side is a controlled construction, giving a documented, real pass and a real fail case
(the exit criterion Phase_14_Master_Development_Roadmap.md REL-016 names explicitly)."""

from datetime import date

from src.agents.nodes.risk_manager import _compute_correlation
from src.agents.state import (
    EquityCurvePoint,
    OptimizationResult,
    StrategyLogic,
    TradingOSGraphState,
)
from src.core.config import get_settings
from src.data.datalake.query import DataLake

_STRATEGY = StrategyLogic(
    hypothesis="index tracker",
    asset_class="Equity",
    style="Swing",
    universe=["RELIANCE"],
    entry_conditions="close > sma_20",
    exit_conditions="close < sma_20",
    stop_loss="2%",
    take_profit="5%",
    position_sizing="fixed",
    confidence_score=0.7,
)


def _real_nifty_closes() -> list[tuple[date, float]]:
    data_lake = DataLake(get_settings().data_lake_root / "ohlcv_daily")
    df = data_lake.read_symbol("^NSEI", None, None).sort("date")
    assert not df.is_empty(), (
        "This test requires real ^NSEI data already ingested -- run "
        "`python -m src.data.ingest.pipeline --source yfinance --symbols ^NSEI "
        "--start 2023-07-21 --end 2024-07-19` first."
    )
    return list(zip(df["date"].to_list(), df["close"].to_list(), strict=True))


def _state_with_equity_curve(equity_curve: list[EquityCurvePoint]) -> TradingOSGraphState:
    return TradingOSGraphState(
        thread_id="t1",
        strategy_logic=_STRATEGY,
        optimization_result=OptimizationResult(passed=True),
        equity_curve=equity_curve,
    )


def test_a_candidate_that_closely_tracks_real_nifty_50_fails_the_correlation_check():
    """Documented FAIL case: an equity curve built directly from the real Nifty 50 closes (a
    near-perfect index tracker) must correlate far above the 0.85 limit against the real
    benchmark series pulled from the same real dates."""
    closes = _real_nifty_closes()
    equity_curve = [EquityCurvePoint(date=d.isoformat(), equity=close) for d, close in closes]

    result = _compute_correlation(_state_with_equity_curve(equity_curve))

    assert result is not None
    assert result.passed is False
    assert result.correlation > 0.85


def test_a_candidate_uncorrelated_with_real_nifty_50_passes_the_correlation_check():
    """Documented PASS case: an equity curve that alternates a fixed +1/-1 daily move
    (independent of the real index's own real day-to-day direction) should show a real,
    low correlation against the real Nifty 50 benchmark series."""
    closes = _real_nifty_closes()
    equity = 100.0
    equity_curve: list[EquityCurvePoint] = []
    for i, (d, _) in enumerate(closes):
        equity *= 1.01 if i % 2 == 0 else 0.99  # a fixed alternating pattern, not index-following
        equity_curve.append(EquityCurvePoint(date=d.isoformat(), equity=equity))

    result = _compute_correlation(_state_with_equity_curve(equity_curve))

    assert result is not None
    assert result.passed is True
    assert result.correlation < 0.85


def test_correlation_is_honestly_none_when_the_candidate_has_no_equity_curve():
    result = _compute_correlation(_state_with_equity_curve([]))
    assert result is None
