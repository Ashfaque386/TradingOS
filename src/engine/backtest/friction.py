"""Indian market friction modeling (Phase 3 Epic E3.2), per
Phase_6_Trading_Engine_Design.md §2:
  - Brokerage: configurable, e.g. Zerodha-style 0.03% or ₹20/order, whichever is lower.
  - STT (Securities Transaction Tax): 0.1% on delivery (both legs), 0.025% on intraday (sell
    leg only) -- exact wording from the design doc.
  - Exchange transaction charges + SEBI turnover fee: precisely modeled per the design doc's
    goal of preventing the AI from generating high-frequency strategies that look profitable
    but lose money to taxes.
  - Stamp duty: not explicitly named in the design doc, but a real, material cost component
    for Indian equity trades -- added here for completeness (buy-side only, standard rate).
  - GST: 18% on brokerage + exchange charges + SEBI fees (not on STT/stamp duty, which are
    themselves taxes, not taxable services).

Rates below are the commonly-documented Zerodha/NSE convention as of this project's build date;
they are configurable, not hardcoded assumptions the AI can't override, and are validated
against manually-derived reference figures in tests/unit/test_friction.py.
"""

from dataclasses import dataclass
from typing import Literal

import pandas as pd

Segment = Literal["delivery", "intraday"]
Side = Literal["buy", "sell"]

BROKERAGE_RATE = 0.0003  # 0.03%
BROKERAGE_CAP = 20.0  # ₹20 per executed order, whichever is lower

STT_RATE_DELIVERY = 0.001  # 0.1%, charged on both legs
STT_RATE_INTRADAY_SELL = 0.00025  # 0.025%, sell leg only

EXCHANGE_CHARGE_RATE = 0.0000297  # NSE equity transaction charge, both legs
SEBI_CHARGE_RATE = 0.000001  # ₹10 per crore, both legs

STAMP_DUTY_RATE_DELIVERY = 0.00015  # buy side only
STAMP_DUTY_RATE_INTRADAY = 0.00003  # buy side only

GST_RATE = 0.18  # on brokerage + exchange charges + SEBI fees only


@dataclass(frozen=True)
class TradeCostBreakdown:
    turnover: float
    brokerage: float
    stt: float
    exchange_charges: float
    sebi_charges: float
    stamp_duty: float
    gst: float

    @property
    def total(self) -> float:
        return (
            self.brokerage
            + self.stt
            + self.exchange_charges
            + self.sebi_charges
            + self.stamp_duty
            + self.gst
        )

    @property
    def fraction_of_turnover(self) -> float:
        return self.total / self.turnover if self.turnover else 0.0


def compute_brokerage(
    turnover: float, *, rate: float = BROKERAGE_RATE, cap: float = BROKERAGE_CAP
) -> float:
    return min(turnover * rate, cap)


def compute_stt(turnover: float, *, segment: Segment, side: Side) -> float:
    if segment == "delivery":
        return turnover * STT_RATE_DELIVERY
    # intraday: sell leg only
    return turnover * STT_RATE_INTRADAY_SELL if side == "sell" else 0.0


def compute_exchange_charges(turnover: float) -> float:
    return turnover * EXCHANGE_CHARGE_RATE


def compute_sebi_charges(turnover: float) -> float:
    return turnover * SEBI_CHARGE_RATE


def compute_stamp_duty(turnover: float, *, segment: Segment, side: Side) -> float:
    if side != "buy":
        return 0.0
    rate = STAMP_DUTY_RATE_DELIVERY if segment == "delivery" else STAMP_DUTY_RATE_INTRADAY
    return turnover * rate


def compute_trade_cost(
    price: float, quantity: float, *, segment: Segment, side: Side
) -> TradeCostBreakdown:
    """Full Indian friction breakdown for a single trade leg (one buy or one sell)."""
    turnover = price * quantity
    brokerage = compute_brokerage(turnover)
    exchange_charges = compute_exchange_charges(turnover)
    sebi_charges = compute_sebi_charges(turnover)
    gst = GST_RATE * (brokerage + exchange_charges + sebi_charges)

    return TradeCostBreakdown(
        turnover=turnover,
        brokerage=brokerage,
        stt=compute_stt(turnover, segment=segment, side=side),
        exchange_charges=exchange_charges,
        sebi_charges=sebi_charges,
        stamp_duty=compute_stamp_duty(turnover, segment=segment, side=side),
        gst=gst,
    )


# --- Dynamic slippage modeling: ATR (volatility) + volume (liquidity), per Phase_6 §2. ---

SLIPPAGE_BASE = 0.0005  # 5 bps floor, even for a highly liquid, low-volatility trade
SLIPPAGE_ATR_COEF = 0.5  # weight applied to (ATR / close) when scaling slippage up
SLIPPAGE_MAX = 0.01  # 100 bps cap, so a single illiquid/volatile bar can't blow up a backtest


def compute_dynamic_slippage(
    close: pd.Series, high: pd.Series, low: pd.Series, volume: pd.Series, *, atr_window: int = 14
) -> pd.Series:
    """Returns a per-row slippage fraction: higher when the symbol is more volatile (wide ATR
    relative to price) or less liquid (volume below its own rolling average) that day. Suitable
    to pass directly as vectorbt's `slippage` parameter."""
    prev_close = close.shift(1)
    true_range = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = true_range.ewm(alpha=1 / atr_window, adjust=False).mean()
    volatility_component = SLIPPAGE_ATR_COEF * (atr / close)

    avg_volume = volume.rolling(atr_window, min_periods=1).mean()
    illiquidity_ratio = (
        (avg_volume / volume.replace(0, pd.NA)).clip(lower=0.5, upper=2.0).fillna(1.0)
    )

    slippage = (SLIPPAGE_BASE + volatility_component) * illiquidity_ratio
    return slippage.clip(lower=SLIPPAGE_BASE, upper=SLIPPAGE_MAX).fillna(SLIPPAGE_BASE)
