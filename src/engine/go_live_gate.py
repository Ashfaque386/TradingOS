"""Go-Live Readiness Gate (Phase 4 Epic E4.4) -- the authoritative multi-condition replacement
for the single "2 weeks" (originally Phase_6_Trading_Engine_Design.md §5) vs. "2 months"
(originally Phase_9_Master_Implementation_Guide.md §1 / Phase_14_Master_Development_Roadmap.md
§5.2-§5.3) paper-trading duration figures. Both were weak calendar-only proxies for the same
underlying question: has this strategy accumulated enough distinct trades, across enough
distinct market conditions, with zero operational failures, that its live behavior can be
trusted to resemble its backtested behavior? See
Phase_14_Master_Development_Roadmap.md §5.4 for the full rationale and the authoritative
definition this module implements.

A strategy clears the gate only when ALL FOUR conditions hold at once:
  1. Trade count               >= MIN_TRADE_COUNT              -- statistical floor
  2. Calendar span              >= MIN_CALENDAR_DAYS             -- >=1 monthly F&O expiry
     cycle, weekend/overnight gaps
  3. Shadow Mode clean streak   >= MIN_CLEAN_DAYS consecutive days, zero broker API errors
  4. Live win rate within WIN_RATE_DIVERGENCE_TOLERANCE of the strategy's latest backtested win rate

All four thresholds are named constants, not magic numbers, so tightening or loosening the gate
later is a one-line, auditable code change -- not a rewrite. Any change here should be
reflected back into Phase_14 §5.4's table.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.engine.paper_trading.position_accounting import replay_ledger
from src.engine.shadow_mode_status import compute_daily_summary, consecutive_clean_days
from src.models.paper_trading import PaperTrade
from src.models.shadow_mode import ShadowModeAttempt
from src.models.strategy import BacktestResult, Strategy

MIN_TRADE_COUNT = 30
MIN_CALENDAR_DAYS = 21
MIN_CLEAN_DAYS = 10
WIN_RATE_DIVERGENCE_TOLERANCE = 0.20  # +/-20 percentage points, since win_rate is a 0..1 fraction


@dataclass(frozen=True)
class GateCondition:
    label: str
    met: bool
    detail: str


@dataclass(frozen=True)
class GoLiveReadiness:
    strategy_id: str
    gate_met: bool
    conditions: list[GateCondition]


def _trade_count_condition(trades: list[PaperTrade]) -> GateCondition:
    filled = [t for t in trades if t.filled_quantity > 0]
    count = len(filled)
    return GateCondition(
        label="Minimum trade count",
        met=count >= MIN_TRADE_COUNT,
        detail=f"{count}/{MIN_TRADE_COUNT} filled paper trades",
    )


def _calendar_span_condition(trades: list[PaperTrade]) -> GateCondition:
    if not trades:
        return GateCondition(
            label="Minimum calendar span",
            met=False,
            detail=f"0/{MIN_CALENDAR_DAYS} days -- no paper trades recorded yet",
        )
    span_days = (trades[-1].executed_at.date() - trades[0].executed_at.date()).days
    return GateCondition(
        label="Minimum calendar span",
        met=span_days >= MIN_CALENDAR_DAYS,
        detail=f"{span_days}/{MIN_CALENDAR_DAYS} days between first and most recent paper trade",
    )


def _shadow_mode_condition(session: Session) -> GateCondition:
    rows = list(session.scalars(select(ShadowModeAttempt).order_by(ShadowModeAttempt.attempted_at)))
    streak = consecutive_clean_days(compute_daily_summary(rows))
    return GateCondition(
        label="Shadow Mode clean streak",
        met=streak >= MIN_CLEAN_DAYS,
        detail=f"{streak}/{MIN_CLEAN_DAYS} consecutive clean broker-validation days",
    )


def _performance_divergence_condition(
    session: Session, strategy: Strategy, trades: list[PaperTrade]
) -> GateCondition:
    label = "Live vs. backtest win-rate divergence"
    _, closes = replay_ledger(trades)
    if not closes:
        return GateCondition(
            label=label,
            met=False,
            detail=(
                "No realized (closed) paper trades yet -- nothing to compare against "
                "the backtest"
            ),
        )
    live_win_rate = sum(1 for c in closes if c.pnl > 0) / len(closes)

    if strategy.current_version_id is None:
        return GateCondition(
            label=label,
            met=False,
            detail="Strategy has no current version -- no backtest to compare against",
        )
    backtest = session.scalars(
        select(BacktestResult)
        .where(BacktestResult.strategy_version_id == strategy.current_version_id)
        .order_by(BacktestResult.created_at.desc())
    ).first()
    if backtest is None or backtest.win_rate is None:
        return GateCondition(
            label=label,
            met=False,
            detail="No backtest win rate on file for the strategy's current version",
        )

    backtest_win_rate = float(backtest.win_rate)
    divergence = abs(live_win_rate - backtest_win_rate)
    return GateCondition(
        label=label,
        met=divergence <= WIN_RATE_DIVERGENCE_TOLERANCE,
        detail=(
            f"live {live_win_rate:.1%} vs. backtest {backtest_win_rate:.1%} "
            f"(divergence {divergence:.1%}, tolerance {WIN_RATE_DIVERGENCE_TOLERANCE:.0%})"
        ),
    )


def compute_readiness(session: Session, strategy: Strategy) -> GoLiveReadiness:
    trades = list(
        session.scalars(
            select(PaperTrade)
            .where(PaperTrade.strategy_id == strategy.id)
            .order_by(PaperTrade.executed_at)
        )
    )
    conditions = [
        _trade_count_condition(trades),
        _calendar_span_condition(trades),
        _shadow_mode_condition(session),
        _performance_divergence_condition(session, strategy, trades),
    ]
    return GoLiveReadiness(
        strategy_id=str(strategy.id),
        gate_met=all(c.met for c in conditions),
        conditions=conditions,
    )
