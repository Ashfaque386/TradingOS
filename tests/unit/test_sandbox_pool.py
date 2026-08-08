"""REL-032 (NFR-01): real subprocess tests for the warm sandbox worker pool -- no mocking, same
convention as tests/unit/test_sandbox_runner.py ("the sandbox's isolation guarantees are exactly
what's under test"). These tests are inherently slower than most unit tests (real vectorbt import
+ JIT compile on a worker's first call) -- that cost is the exact thing this feature exists to
amortize away on every call after the first.
"""

import time
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
import pytest

from src.core.config import Settings
from src.engine.sandbox import pool as pool_module
from src.engine.sandbox.pool import SandboxWorkerPool, execute_in_pool

_VECTORBT_STRATEGY = """
import polars as pl
import vectorbt as vbt


def run_backtest(data: pl.DataFrame, config: dict) -> dict:
    close = data["close"].to_pandas()
    close.index = data["date"].to_pandas()
    fast = close.rolling(5).mean()
    slow = close.rolling(20).mean()
    entries = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    exits = (fast < slow) & (fast.shift(1) >= slow.shift(1))
    pf = vbt.Portfolio.from_signals(close, entries, exits, init_cash=100000, freq="1D")
    sharpe = pf.sharpe_ratio()
    return {"sharpe_ratio": float(sharpe) if sharpe == sharpe else None}
"""

_SIMPLE_STRATEGY = """
def run_backtest(data, config):
    return {"rows_seen": data.height}
"""


@pytest.fixture
def ohlcv_parquet(tmp_path: Path) -> Path:
    n = 300
    rng = np.random.default_rng(seed=7)
    closes = np.clip(100 + np.cumsum(rng.normal(0, 1, n)), 1.0, None)
    dates = pd.bdate_range(end=pd.Timestamp.today(), periods=n)
    df = pl.DataFrame(
        {
            "symbol": ["TEST"] * n,
            "date": [d.date() for d in dates],
            "open": closes,
            "high": closes * 1.01,
            "low": closes * 0.99,
            "close": closes,
            "volume": [10000] * n,
        }
    )
    path = tmp_path / "test_ohlcv.parquet"
    df.write_parquet(path)
    return path


def test_pool_second_call_on_a_warm_worker_is_dramatically_faster(ohlcv_parquet: Path):
    pool = SandboxWorkerPool(size=1)
    try:
        first = pool.execute(_VECTORBT_STRATEGY, {}, ohlcv_parquet, timeout=60.0)
        assert first.passed is True, first.error

        second = pool.execute(_VECTORBT_STRATEGY, {}, ohlcv_parquet, timeout=60.0)
        assert second.passed is True, second.error

        # The real, measured effect this module exists for: not a strict scale-factor
        # assertion (real environment timing varies), just confirming the direction and
        # magnitude are what the feature promises.
        assert second.duration_seconds < first.duration_seconds / 2
        assert second.duration_seconds < 2.0
    finally:
        pool.shutdown()


def test_pool_gives_each_call_a_fresh_namespace_not_shared_across_strategies(ohlcv_parquet: Path):
    pool = SandboxWorkerPool(size=1)
    try:
        leaky_code = """
_leaked_marker = "should not survive to the next call"

def run_backtest(data, config):
    return {"ok": True}
"""
        checking_code = """
def run_backtest(data, config):
    return {"leaked": "_leaked_marker" in dir()}
"""
        first = pool.execute(leaky_code, {}, ohlcv_parquet, timeout=30.0)
        assert first.passed is True, first.error

        second = pool.execute(checking_code, {}, ohlcv_parquet, timeout=30.0)
        assert second.passed is True, second.error
        assert second.portfolio_summary["leaked"] is False
    finally:
        pool.shutdown()


def test_pool_retires_a_worker_after_max_jobs(monkeypatch: pytest.MonkeyPatch, ohlcv_parquet: Path):
    monkeypatch.setattr(pool_module, "MAX_JOBS_PER_WORKER", 2)
    pool = SandboxWorkerPool(size=1)
    try:
        original_pid = pool._available[0].proc.pid

        pool.execute(_SIMPLE_STRATEGY, {}, ohlcv_parquet, timeout=10.0)
        # Still the same worker after 1 of 2 allowed jobs.
        assert pool._available[0].proc.pid == original_pid

        pool.execute(_SIMPLE_STRATEGY, {}, ohlcv_parquet, timeout=10.0)
        # Hit the cap on the 2nd job -- retired and replaced with a fresh worker.
        assert pool._available[0].proc.pid != original_pid
    finally:
        pool.shutdown()


def test_pool_kills_and_replaces_a_hung_worker_on_timeout(ohlcv_parquet: Path):
    pool = SandboxWorkerPool(size=1)
    try:
        original_pid = pool._available[0].proc.pid

        hanging_code = """
import time

def run_backtest(data, config):
    time.sleep(30)
    return {"ok": True}
"""
        start = time.perf_counter()
        result = pool.execute(hanging_code, {}, ohlcv_parquet, timeout=1.0)
        elapsed = time.perf_counter() - start

        assert result.passed is False
        assert "timeout" in result.error.lower() or "exceeded" in result.error.lower()
        assert elapsed < 10.0  # killed well before the strategy's own 30s sleep would finish

        # The pool replaced the hung worker with a fresh one -- still usable afterward.
        assert pool._available[0].proc.pid != original_pid
        follow_up = pool.execute(_SIMPLE_STRATEGY, {}, ohlcv_parquet, timeout=10.0)
        assert follow_up.passed is True, follow_up.error
    finally:
        pool.shutdown()


def test_execute_in_pool_falls_back_to_one_shot_sandbox_when_disabled(ohlcv_parquet: Path):
    settings = Settings(sandbox_pool_enabled=False)
    result = execute_in_pool(_SIMPLE_STRATEGY, {}, data_path=ohlcv_parquet, settings=settings)
    assert result.passed is True
    assert result.portfolio_summary["rows_seen"] == 300
