"""Layer 1 of the Paper Trading Account's two-layer execution engine (REL-034): the once-per-
real-trading-day directional signal, per strategy in `"PaperTrading"` status.

Reuses the existing, already-tested strategy execution path unmodified -- `run_real_backtest`
(src/engine/sandbox/backtest_runner.py, itself the warm sandbox pool from REL-032) re-runs a
strategy's own code through the most recent real EOD close, and this module reads off the
resulting `entries_exits` series' LAST point the exact same way REL-024's Walk-Forward adapter
already reuses that series for rolling-window replay -- no new strategy-code re-invocation
mechanism, no bar aggregation, no change to the daily-bar semantics the code was validated
against. `entries[t]=True` means "go long," `exits[t]=True` means "close the long" -- the
standard vectorbt `Portfolio.from_signals` long-only convention every strategy here already
uses (confirmed via walk_forward_adapter.py's own identical reading of this same field).

A signal only produces a trade on a genuine TRANSITION from the strategy's current real paper
position (flat -> long fires BUY, long -> flat fires SELL), restored via `replay_ledger()` on
that strategy's own trade history -- so a scheduler restart never re-fires an already-open
position. Position size comes from the same hardcoded, tested `compute_position_sizes()`
(src/engine/risk/position_sizing.py) Stage 4 wires into the agent graph, splitting the paper
account's live equity evenly across every strategy active this cycle (an equal-weight approx --
no per-strategy capital-allocation field exists to size against directly).

REL-035: F&O strategies (`Strategy.asset_class == "F&O"`) now trade too, once the Options
Strategy Agent's chain-grounded legs are actually persisted (`StrategyVersion.option_legs`/
`option_expiry`, src/api/routers/agents.py::_persist_strategy_progress) -- the same
`entries_exits` transition signal still drives *when* to act (unchanged, see above); *what* to
trade is read off the persisted legs instead of the equity path's single symbol + position
sizing. A version with no persisted legs (never grounded, or generation degraded) or a persisted
expiry that has passed is honestly skipped, never guessed at or auto-rolled to a fresh expiry no
one reviewed -- see `_process_fno_strategy`.

Named, not silently assumed away: multi-leg atomicity. `execute_paper_trade` commits each leg
independently (its own session, its own commit) -- there is no atomic multi-leg order primitive
in this codebase, and a paper fill is a persisted fact, not a cancellable order. If one leg of a
spread fills and the next then fails (a real `NoLiquidityError` or broker timeout), the first
leg's `PaperTrade` row is already real and not rolled back. `_process_fno_strategy` catches
per-leg, not per-strategy, and reports a new `"PARTIAL_FILL"` result kind naming exactly which
legs filled -- never silently reporting `"SKIPPED"` when a real state change actually happened.
No same-cycle auto-repair is attempted; a partial spread surfaces for the next cycle's per-leg
open/closed detection (and likely human review), not a same-day guess at completing it.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pandas as pd
import structlog
from sqlalchemy import select

from src.agents.control import is_agent_enabled
from src.brokers.base import Side
from src.brokers.factory import NoBrokerConfigured, build_broker
from src.core.config import get_settings
from src.core.db import get_session
from src.data.datalake.query import DataLake
from src.data.reference.nse_holiday_calendar import is_trading_holiday, previous_trading_day
from src.engine.paper_trading.account_equity import compute_account_equity
from src.engine.paper_trading.execution_service import execute_paper_trade
from src.engine.paper_trading.paper_account import get_paper_account
from src.engine.paper_trading.paper_kill_switch import update_and_check
from src.engine.paper_trading.position_accounting import replay_ledger
from src.engine.risk.position_sizing import compute_position_sizes
from src.engine.sandbox.backtest_runner import run_real_backtest
from src.models.paper_trading import PaperTrade
from src.models.strategy import Strategy, StrategyVersion

logger = structlog.get_logger(__name__)

PAPER_TRADING_AGENT_NAME = "paper_trading_engine"
BACKTEST_LOOKBACK_DAYS = 730

# REL-035: bridges StrategyOptionLeg.side (lowercase, LLM/schema convention, src/agents/state.py)
# to execute_paper_trade's uppercase Side (broker-adapter convention, src/brokers/base.py) -- no
# such mapping existed anywhere before this, every existing caller was consistently one case or
# the other, never both.
_SIDE_MAP: dict[str, Side] = {"buy": "BUY", "sell": "SELL"}
_CLOSING_SIDE_MAP: dict[str, Side] = {"buy": "SELL", "sell": "BUY"}


@dataclass(frozen=True)
class StrategyCycleResult:
    strategy_id: str
    action: str  # "BUY" | "SELL" | "NO_TRANSITION" | "SKIPPED" | "PARTIAL_FILL"
    reason: str | None = None
    trade_id: str | None = None


async def _process_strategy(
    strategy: Strategy, *, account_id: str, total_capital: float, not_after: date
) -> StrategyCycleResult:
    sid = str(strategy.id)

    if strategy.asset_class == "F&O":
        return await _process_fno_strategy(strategy, account_id=account_id, not_after=not_after)
    if not strategy.universe:
        return StrategyCycleResult(sid, "SKIPPED", "strategy has no universe")
    if strategy.current_version_id is None:
        return StrategyCycleResult(sid, "SKIPPED", "strategy has no current code version")

    symbol = strategy.universe[0]
    # The data lake's own most recent ingested date, not date.today() -- the two are NOT the
    # same thing (a real production ingestion pipeline could lag; this dev environment's own
    # lake is a fixed historical dataset far behind the system clock). `not_after` is a sanity
    # ceiling only (never backtest into a bogus future-dated row), not the primary source of
    # truth for "what's the latest real data."
    lake = DataLake(get_settings().data_lake_root / "ohlcv_daily")
    lake_latest = lake.latest_date(symbol)
    if lake_latest is None:
        return StrategyCycleResult(sid, "SKIPPED", f"no historical data ingested for {symbol}")
    date_to = min(lake_latest, not_after)

    with get_session() as session:
        version = session.get(StrategyVersion, strategy.current_version_id)
        if version is None:
            return StrategyCycleResult(sid, "SKIPPED", "current_version_id points at a missing row")
        code = version.python_code

        existing_trades = list(
            session.execute(
                select(PaperTrade)
                .where(PaperTrade.strategy_id == strategy.id)
                .order_by(PaperTrade.executed_at.asc())
            )
            .scalars()
            .all()
        )

    positions, _ = replay_ledger(existing_trades)
    currently_long = positions.get(symbol, None) is not None and positions[symbol].net_quantity > 0

    outcome = run_real_backtest(
        code,
        universe=strategy.universe,
        date_from=date_to - timedelta(days=BACKTEST_LOOKBACK_DAYS),
        date_to=date_to,
    )
    if not outcome.passed or not outcome.entries_exits:
        return StrategyCycleResult(
            sid, "SKIPPED", outcome.error or "no entries_exits signal produced"
        )

    latest = outcome.entries_exits[-1]
    action: Side
    if latest.entry and not currently_long:
        action = "BUY"
    elif latest.exit and currently_long:
        action = "SELL"
    else:
        return StrategyCycleResult(sid, "NO_TRANSITION")

    if action == "SELL":
        quantity = positions[symbol].net_quantity
    else:
        closes = outcome.close_curve
        if len(closes) < 2:
            return StrategyCycleResult(sid, "SKIPPED", "not enough close history to size a trade")
        returns = pd.Series([c.close for c in closes]).pct_change().dropna()
        last_price = closes[-1].close
        sizes = compute_position_sizes(
            {symbol: returns}, {symbol: last_price}, total_capital=total_capital
        )
        quantity = sizes[symbol].shares if symbol in sizes else 0
        if quantity <= 0:
            return StrategyCycleResult(sid, "SKIPPED", "computed position size was zero")

    try:
        broker = build_broker()
    except NoBrokerConfigured as exc:
        return StrategyCycleResult(sid, "SKIPPED", f"no broker configured: {exc}")

    try:
        trade = await execute_paper_trade(
            broker,
            symbol=symbol,
            side=action,
            quantity=quantity,
            account_id=account_id,
            strategy_id=sid,
            instrument_type="EQUITY",
        )
    except (
        Exception
    ) as exc:  # noqa: BLE001 -- a real failure for THIS strategy must not abort the whole cycle
        return StrategyCycleResult(sid, "SKIPPED", f"execution failed: {exc}")

    return StrategyCycleResult(sid, action, trade_id=str(trade.id))


async def _process_fno_strategy(
    strategy: Strategy, *, account_id: str, not_after: date
) -> StrategyCycleResult:
    """REL-035: the F&O counterpart to `_process_strategy` above -- same `entries_exits`
    transition signal, but trades the persisted, chain-grounded legs (`StrategyVersion.
    option_legs`/`option_expiry`) instead of a single symbol + computed position size. See this
    module's own docstring for the multi-leg atomicity limitation this deliberately does not
    paper over."""
    sid = str(strategy.id)
    if not strategy.universe:
        return StrategyCycleResult(sid, "SKIPPED", "strategy has no universe")
    if strategy.current_version_id is None:
        return StrategyCycleResult(sid, "SKIPPED", "strategy has no current code version")

    underlying = strategy.universe[0]
    lake = DataLake(get_settings().data_lake_root / "ohlcv_daily")
    lake_latest = lake.latest_date(underlying)
    if lake_latest is None:
        return StrategyCycleResult(sid, "SKIPPED", f"no historical data ingested for {underlying}")
    date_to = min(lake_latest, not_after)

    with get_session() as session:
        version = session.get(StrategyVersion, strategy.current_version_id)
        if version is None:
            return StrategyCycleResult(sid, "SKIPPED", "current_version_id points at a missing row")
        code = version.python_code
        legs: list[dict[str, Any]] | None = version.option_legs
        expiry = version.option_expiry

        existing_trades = list(
            session.execute(
                select(PaperTrade)
                .where(PaperTrade.strategy_id == strategy.id)
                .order_by(PaperTrade.executed_at.asc())
            )
            .scalars()
            .all()
        )

    if not legs or expiry is None:
        return StrategyCycleResult(
            sid, "SKIPPED", "no grounded option legs persisted for the current version"
        )
    if expiry < date.today():
        return StrategyCycleResult(sid, "SKIPPED", f"persisted option plan expired on {expiry}")

    positions, _ = replay_ledger(existing_trades)
    leg_open = {
        leg["symbol"]: positions.get(leg["symbol"]) is not None
        and positions[leg["symbol"]].net_quantity != 0
        for leg in legs
    }
    all_open = all(leg_open.values())
    any_open = any(leg_open.values())

    outcome = run_real_backtest(
        code,
        universe=strategy.universe,
        date_from=date_to - timedelta(days=BACKTEST_LOOKBACK_DAYS),
        date_to=date_to,
    )
    if not outcome.passed or not outcome.entries_exits:
        return StrategyCycleResult(
            sid, "SKIPPED", outcome.error or "no entries_exits signal produced"
        )

    latest = outcome.entries_exits[-1]
    if latest.entry and not all_open:
        intent = "BUY"  # entering: only the legs not already open
        legs_to_execute = [leg for leg in legs if not leg_open[leg["symbol"]]]
    elif latest.exit and any_open:
        intent = "SELL"  # exiting: only the legs actually open
        legs_to_execute = [leg for leg in legs if leg_open[leg["symbol"]]]
    else:
        return StrategyCycleResult(sid, "NO_TRANSITION")

    try:
        broker = build_broker()
    except NoBrokerConfigured as exc:
        return StrategyCycleResult(sid, "SKIPPED", f"no broker configured: {exc}")

    filled: list[tuple[str, str]] = []
    failed: list[str] = []
    for leg in legs_to_execute:
        leg_symbol = str(leg["symbol"])
        leg_side_key = str(leg["side"])
        if intent == "BUY":
            leg_side = _SIDE_MAP[leg_side_key]
            quantity = int(leg["quantity"])
        else:
            leg_side = _CLOSING_SIDE_MAP[leg_side_key]
            open_position = positions.get(leg_symbol)
            quantity = abs(open_position.net_quantity) if open_position else int(leg["quantity"])
        if quantity <= 0:
            continue

        try:
            trade = await execute_paper_trade(
                broker,
                symbol=leg_symbol,
                side=leg_side,
                quantity=quantity,
                account_id=account_id,
                strategy_id=sid,
                instrument_type=str(leg["option_type"]),
                underlying=underlying,
                strike=float(leg["strike"]),
                expiry=expiry,
            )
        except (
            Exception
        ) as exc:  # noqa: BLE001 -- per-leg, not per-strategy: a spread can partially fill
            failed.append(f"{leg_symbol}: {exc}")
            continue
        filled.append((leg_symbol, str(trade.id)))

    if not filled:
        return StrategyCycleResult(
            sid, "SKIPPED", f"all legs failed to execute: {'; '.join(failed)}"
        )
    if failed:
        return StrategyCycleResult(
            sid,
            "PARTIAL_FILL",
            f"filled {[s for s, _ in filled]}; failed: {'; '.join(failed)}",
            trade_id=",".join(tid for _, tid in filled),
        )
    return StrategyCycleResult(sid, intent, trade_id=",".join(tid for _, tid in filled))


async def run_daily_paper_trading_cycle() -> list[StrategyCycleResult]:
    """The real, once-per-trading-day entry point -- scheduled via src/agents/scheduler.py's
    own CronTrigger pattern, shortly after the existing 06:00 research cycle so an overnight
    decision executes at a real live-market-open quote."""
    if is_trading_holiday(date.today()):
        logger.info("paper_trading_daily_cycle_skipped", reason="not a real NSE trading day")
        return []

    with get_session() as session:
        if not is_agent_enabled(session, PAPER_TRADING_AGENT_NAME):
            logger.info("paper_trading_daily_cycle_skipped_disabled")
            return []

        account = get_paper_account(session)
        strategies = list(
            session.execute(select(Strategy).where(Strategy.status == "PaperTrading"))
            .scalars()
            .all()
        )

    if not strategies:
        logger.info("paper_trading_daily_cycle_skipped", reason="no PaperTrading strategies")
        return []

    try:
        broker = build_broker()
        with get_session() as session:
            equity = await compute_account_equity(str(account.id), session, broker)
    except NoBrokerConfigured:
        logger.warning("paper_trading_daily_cycle_skipped", reason="no broker configured")
        return []

    if not update_and_check(equity):
        logger.warning("paper_trading_daily_cycle_halted", reason="paper kill switch tripped")
        return []

    # This runs pre-market, shortly after the 06:00 research cycle -- today's own EOD bar
    # cannot exist yet, so the most recent COMPLETED trading day is the sanity ceiling (see
    # _process_strategy's own comment for why the data lake's own latest date is what actually
    # governs the query window, not this value directly).
    not_after = previous_trading_day(date.today())
    total_capital_per_strategy = equity / len(strategies)

    results = []
    for strategy in strategies:
        result = await _process_strategy(
            strategy,
            account_id=str(account.id),
            total_capital=total_capital_per_strategy,
            not_after=not_after,
        )
        results.append(result)
        logger.info(
            "paper_trading_daily_cycle_strategy_result",
            strategy_id=result.strategy_id,
            action=result.action,
            reason=result.reason,
        )

    return results
