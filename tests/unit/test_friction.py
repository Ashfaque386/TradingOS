"""Indian market friction modeling tests (Phase 3 Epic E3.2 exit criterion): validated against
manually-derived reference figures.

Reference calculation (delivery, buy 100 @ 2500, sell 100 @ 2600):
  Buy turnover  = 250,000
    brokerage       = min(0.0003*250000, 20)      = 20
    STT (delivery)  = 0.001*250000                = 250
    exchange chg    = 0.0000297*250000            = 7.425
    SEBI chg        = 0.000001*250000             = 0.25
    stamp duty (buy)= 0.00015*250000              = 37.5
    GST             = 0.18*(20+7.425+0.25)        = 4.9815
    TOTAL           = 320.1565
  Sell turnover = 260,000
    brokerage       = min(0.0003*260000, 20)      = 20
    STT (delivery)  = 0.001*260000                = 260
    exchange chg    = 0.0000297*260000            = 7.722
    SEBI chg        = 0.000001*260000             = 0.26
    stamp duty (sell)= 0 (buy-side only)
    GST             = 0.18*(20+7.722+0.26)        = 5.03676
    TOTAL           = 293.01876
"""

import pandas as pd
import pytest

from src.engine.backtest.friction import (
    compute_brokerage,
    compute_dynamic_slippage,
    compute_exchange_charges,
    compute_sebi_charges,
    compute_stamp_duty,
    compute_stt,
    compute_trade_cost,
)

TOLERANCE = 1e-6


def test_brokerage_is_capped_at_20_rupees():
    # 0.03% of 250,000 = 75, above the ₹20 cap
    assert compute_brokerage(250_000) == pytest.approx(20.0, abs=TOLERANCE)


def test_brokerage_uses_percentage_when_below_cap():
    # 0.03% of 1,000 = 0.30, below the ₹20 cap
    assert compute_brokerage(1_000) == pytest.approx(0.30, abs=TOLERANCE)


def test_stt_delivery_applies_to_both_legs():
    assert compute_stt(250_000, segment="delivery", side="buy") == pytest.approx(250.0)
    assert compute_stt(260_000, segment="delivery", side="sell") == pytest.approx(260.0)


def test_stt_intraday_applies_to_sell_leg_only():
    assert compute_stt(250_000, segment="intraday", side="buy") == pytest.approx(0.0)
    assert compute_stt(260_000, segment="intraday", side="sell") == pytest.approx(65.0)


def test_exchange_and_sebi_charges():
    assert compute_exchange_charges(250_000) == pytest.approx(7.425, abs=TOLERANCE)
    assert compute_sebi_charges(250_000) == pytest.approx(0.25, abs=TOLERANCE)


def test_stamp_duty_delivery_buy_side_only():
    assert compute_stamp_duty(250_000, segment="delivery", side="buy") == pytest.approx(37.5)
    assert compute_stamp_duty(250_000, segment="delivery", side="sell") == pytest.approx(0.0)


def test_manual_reference_delivery_buy_leg():
    breakdown = compute_trade_cost(2500.0, 100, segment="delivery", side="buy")
    assert breakdown.turnover == pytest.approx(250_000.0)
    assert breakdown.brokerage == pytest.approx(20.0, abs=TOLERANCE)
    assert breakdown.stt == pytest.approx(250.0, abs=TOLERANCE)
    assert breakdown.exchange_charges == pytest.approx(7.425, abs=TOLERANCE)
    assert breakdown.sebi_charges == pytest.approx(0.25, abs=TOLERANCE)
    assert breakdown.stamp_duty == pytest.approx(37.5, abs=TOLERANCE)
    assert breakdown.gst == pytest.approx(4.9815, abs=TOLERANCE)
    assert breakdown.total == pytest.approx(320.1565, abs=1e-4)


def test_manual_reference_delivery_sell_leg():
    breakdown = compute_trade_cost(2600.0, 100, segment="delivery", side="sell")
    assert breakdown.turnover == pytest.approx(260_000.0)
    assert breakdown.brokerage == pytest.approx(20.0, abs=TOLERANCE)
    assert breakdown.stt == pytest.approx(260.0, abs=TOLERANCE)
    assert breakdown.exchange_charges == pytest.approx(7.722, abs=TOLERANCE)
    assert breakdown.sebi_charges == pytest.approx(0.26, abs=TOLERANCE)
    assert breakdown.stamp_duty == pytest.approx(0.0, abs=TOLERANCE)
    assert breakdown.gst == pytest.approx(5.03676, abs=TOLERANCE)
    assert breakdown.total == pytest.approx(293.01876, abs=1e-4)


def test_manual_reference_intraday_buy_leg():
    breakdown = compute_trade_cost(2500.0, 100, segment="intraday", side="buy")
    assert breakdown.stt == pytest.approx(0.0)
    assert breakdown.stamp_duty == pytest.approx(7.5, abs=TOLERANCE)
    assert breakdown.total == pytest.approx(40.1565, abs=1e-4)


def test_manual_reference_intraday_sell_leg():
    breakdown = compute_trade_cost(2600.0, 100, segment="intraday", side="sell")
    assert breakdown.stt == pytest.approx(65.0, abs=TOLERANCE)
    assert breakdown.stamp_duty == pytest.approx(0.0, abs=TOLERANCE)
    assert breakdown.total == pytest.approx(98.01876, abs=1e-4)


def test_dynamic_slippage_stays_within_bounds():
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    close = pd.Series([100 + i * 0.5 for i in range(30)], index=dates)
    high = close + 2
    low = close - 2
    volume = pd.Series([10_000] * 30, index=dates)

    slippage = compute_dynamic_slippage(close, high, low, volume)

    assert (slippage >= 0.0005 - 1e-9).all()
    assert (slippage <= 0.01 + 1e-9).all()
    assert not slippage.isna().any()


def test_dynamic_slippage_increases_with_volatility():
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    close = pd.Series([100.0] * 30, index=dates)
    volume = pd.Series([10_000] * 30, index=dates)

    calm_slippage = compute_dynamic_slippage(close, close + 0.5, close - 0.5, volume)
    volatile_slippage = compute_dynamic_slippage(close, close + 5, close - 5, volume)

    assert volatile_slippage.iloc[-1] > calm_slippage.iloc[-1]


def test_dynamic_slippage_increases_with_illiquidity():
    # Spread kept narrow (unlike the volatility test above) so the ATR-driven component
    # stays well under SLIPPAGE_MAX -- otherwise the illiquidity multiplier's effect gets
    # clipped away and both series saturate to the same capped value.
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    close = pd.Series([100.0] * 30, index=dates)
    high = close + 0.2
    low = close - 0.2

    liquid_volume = pd.Series([10_000] * 30, index=dates)
    illiquid_volume = pd.Series([10_000] * 29 + [500], index=dates)

    liquid_slippage = compute_dynamic_slippage(close, high, low, liquid_volume)
    illiquid_slippage = compute_dynamic_slippage(close, high, low, illiquid_volume)

    assert illiquid_slippage.iloc[-1] > liquid_slippage.iloc[-1]
