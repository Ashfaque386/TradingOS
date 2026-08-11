"""Paper Trading Engine endpoints (Phase 4 Epic E4.4), backing
Phase_6_Trading_Engine_Design.md §5: "A strategy must survive paper trading ... before the CEO
Agent can recommend it for Live deployment." Phase_6 originally said 2 weeks and
Phase_14_Master_Development_Roadmap.md originally said 2 months for the same gate; that
discrepancy is now resolved by Phase_14 §5.4's authoritative Go-Live Readiness Gate (see
src/engine/go_live_gate.py), which replaces both fixed-duration figures with four independently
verified conditions. This router still only ever produces the raw ledger the gate reads from --
it does not itself decide readiness.

Every simulated fill is real depth-walked math against a real live broker quote (see
src/engine/paper_trading/execution_service.py) -- nothing here ever calls place_order. Position
PnL uses the average-cost-basis method (each closing trade realizes PnL against the position's
running weighted-average entry price), not FIFO lot matching -- a real, standard, but simplified
accounting choice, documented here rather than silently assumed.

UPDATE 2026-08-01 (SEC-046, found during a paper-trading-dashboard research pass): POST /execute
had NO auth dependency at all -- any unauthenticated caller could trigger a real depth-walked
broker quote call and write rows into the same paper_trades ledger the Go-Live Readiness Gate
(src/engine/go_live_gate.py) counts trades from. Gated to the same SystemAdministrator/
PortfolioManager/RiskManager set used for POST /strategies/{id}/backtest (an equivalent-weight
operational action, same precedent as REL-011 E10.11.0/SEC-045). GET /trades and GET /positions
stay open (Any role, matching this codebase's existing read-endpoint convention) -- only the
mutating call was ever the gap.
"""

import csv
import io
import uuid
from datetime import date, datetime
from typing import Literal

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import require_role
from src.brokers.base import BrokerAdapter, Side
from src.brokers.factory import NoBrokerConfigured, build_broker
from src.core.db import get_session
from src.core.security import ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER, ROLE_SYSTEM_ADMINISTRATOR
from src.engine.paper_trading.account_equity import compute_equity_from_positions
from src.engine.paper_trading.execution_service import NoLiquidityError, execute_paper_trade
from src.engine.paper_trading.margin_model import compute_margin_summary
from src.engine.paper_trading.paper_account import get_paper_account
from src.engine.paper_trading.position_accounting import SymbolPosition as SymbolPositionAcct
from src.engine.paper_trading.position_accounting import replay_ledger
from src.models.account import Account, AccountEquitySnapshot
from src.models.paper_trading import PaperTrade
from src.models.user import User

router = APIRouter(prefix="/api/v1/paper-trading", tags=["paper-trading"])
logger = structlog.get_logger(__name__)

_can_execute_paper_trade = require_role(
    ROLE_SYSTEM_ADMINISTRATOR, ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER, audit_denials=True
)


class ExecuteRequest(BaseModel):
    symbol: str
    side: Side
    quantity: int
    strategy_id: uuid.UUID | None = None


class PaperTradeResponse(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    strategy_id: uuid.UUID | None
    instrument_type: str
    symbol: str
    side: str
    requested_quantity: int
    filled_quantity: int
    reference_price: float
    fill_price: float
    slippage_bps: float
    executed_at: datetime


def _to_response(trade: PaperTrade) -> PaperTradeResponse:
    return PaperTradeResponse(
        id=trade.id,
        account_id=trade.account_id,
        strategy_id=trade.strategy_id,
        instrument_type=trade.instrument_type,
        symbol=trade.symbol,
        side=trade.side,
        requested_quantity=trade.requested_quantity,
        filled_quantity=trade.filled_quantity,
        reference_price=float(trade.reference_price),
        fill_price=float(trade.fill_price),
        slippage_bps=float(trade.slippage_bps),
        executed_at=trade.executed_at,
    )


@router.post("/execute", response_model=PaperTradeResponse, status_code=201)
async def execute(
    body: ExecuteRequest, _user: User = Depends(_can_execute_paper_trade)
) -> PaperTradeResponse:
    try:
        broker = build_broker()
    except NoBrokerConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    with get_session() as session:
        try:
            account_id = str(get_paper_account(session).id)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        trade = await execute_paper_trade(
            broker,
            symbol=body.symbol,
            side=body.side,
            quantity=body.quantity,
            account_id=account_id,
            strategy_id=str(body.strategy_id) if body.strategy_id else None,
        )
    except NoLiquidityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        # The real broker's quote call failed (e.g. an expired daily access token -- both
        # Zerodha and Upstox tokens expire every trading day with no refresh token, a
        # documented constraint, not something this endpoint can paper over). 502: the failure
        # is upstream, not a bad request from our own caller.
        raise HTTPException(status_code=502, detail=f"Broker quote request failed: {exc}") from exc
    return _to_response(trade)


@router.get("/trades", response_model=list[PaperTradeResponse])
def list_trades(strategy_id: uuid.UUID | None = None) -> list[PaperTradeResponse]:
    with get_session() as session:
        query = select(PaperTrade).order_by(PaperTrade.executed_at)
        if strategy_id is not None:
            query = query.where(PaperTrade.strategy_id == strategy_id)
        trades = session.scalars(query)
        return [_to_response(t) for t in trades]


class SymbolPosition(BaseModel):
    symbol: str
    net_quantity: int
    average_cost: float | None
    realized_pnl: float
    trade_count: int


@router.get("/positions", response_model=list[SymbolPosition])
def get_positions(strategy_id: uuid.UUID | None = None) -> list[SymbolPosition]:
    """Average-cost-basis position rollup, computed fresh from the real trade ledger every call
    (no separate positions table to drift out of sync with it)."""
    with get_session() as session:
        query = select(PaperTrade).order_by(PaperTrade.executed_at)
        if strategy_id is not None:
            query = query.where(PaperTrade.strategy_id == strategy_id)
        trades = list(session.scalars(query))

    positions, _ = replay_ledger(trades)
    return [
        SymbolPosition(
            symbol=pos.symbol,
            net_quantity=pos.net_quantity,
            average_cost=pos.average_cost if pos.net_quantity != 0 else None,
            realized_pnl=round(pos.realized_pnl, 2),
            trade_count=pos.trade_count,
        )
        for pos in positions.values()
    ]


# ---------------------------------------------------------------------------------------------
# REL-034: Account summary / statement -- the broker-style report section. Reads stay open (no
# new role gate), matching the existing GET /trades and /positions convention above: a paper
# account risks no real capital, so there's no equivalent-weight reason to gate it tighter than
# the rest of this router already is.
# ---------------------------------------------------------------------------------------------


def _account_and_trades(session: Session) -> tuple[Account, list[PaperTrade]]:
    account = get_paper_account(session)
    trades = list(
        session.execute(
            select(PaperTrade)
            .where(PaperTrade.account_id == account.id)
            .order_by(PaperTrade.executed_at.asc())
        )
        .scalars()
        .all()
    )
    return account, trades


async def _fetch_last_prices(
    broker: BrokerAdapter, positions: dict[str, SymbolPositionAcct]
) -> dict[str, float]:
    """Same on-demand real-quote pattern src/api/routers/portfolio.py already uses for the real
    account -- bounded by currently-open symbols only, never a standing subscriber. A quote
    fetch failing for one symbol is a real, honest gap (excluded, not fabricated)."""
    last_prices: dict[str, float] = {}
    for symbol, pos in positions.items():
        if pos.net_quantity == 0:
            continue
        try:
            quote = await broker.get_quote(symbol)
            last_prices[symbol] = quote.last_price
        except Exception as exc:  # noqa: BLE001 -- one symbol's failure must not stop the rest
            logger.warning("account_summary_quote_fetch_failed", symbol=symbol, error=str(exc))
            continue
    return last_prices


class AccountSummaryResponse(BaseModel):
    account_id: uuid.UUID
    starting_capital: float
    cash: float
    margin_blocked: float
    realized_pnl_total: float
    unrealized_pnl_total: float
    realized_pnl_by_instrument_class: dict[str, float]
    equity: float


@router.get("/account/summary", response_model=AccountSummaryResponse)
async def account_summary() -> AccountSummaryResponse:
    with get_session() as session:
        try:
            account, trades = _account_and_trades(session)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    positions, _closes = replay_ledger(trades)

    try:
        broker = build_broker()
        last_prices = await _fetch_last_prices(broker, positions)
    except NoBrokerConfigured:
        last_prices = {}

    realized_by_class: dict[str, float] = {}
    for pos in positions.values():
        realized_by_class[pos.instrument_type] = (
            realized_by_class.get(pos.instrument_type, 0.0) + pos.realized_pnl
        )

    realized_total = sum(p.realized_pnl for p in positions.values())
    unrealized_total = sum(
        (last_prices[symbol] - p.average_cost) * p.net_quantity
        for symbol, p in positions.items()
        if p.net_quantity != 0 and symbol in last_prices
    )
    margin_blocked = compute_margin_summary(positions, last_prices).total_margin_blocked
    starting_capital = float(account.capital_allocated)
    cash = starting_capital + realized_total
    equity = compute_equity_from_positions(starting_capital, positions, last_prices)

    return AccountSummaryResponse(
        account_id=account.id,
        starting_capital=starting_capital,
        cash=round(cash, 2),
        margin_blocked=round(margin_blocked, 2),
        realized_pnl_total=round(realized_total, 2),
        unrealized_pnl_total=round(unrealized_total, 2),
        realized_pnl_by_instrument_class={k: round(v, 2) for k, v in realized_by_class.items()},
        equity=round(equity, 2),
    )


class EquityCurvePointResponse(BaseModel):
    snapshot_date: date
    equity: float
    cash: float
    unrealized_pnl: float
    margin_blocked: float


@router.get("/account/equity-curve", response_model=list[EquityCurvePointResponse])
async def account_equity_curve(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
) -> list[EquityCurvePointResponse]:
    """Historical `AccountEquitySnapshot` rows (one per real trading day, written by
    src/agents/scheduler.py's daily job) plus one live-computed point for "today" -- so the
    chart never trails a stale gap while today's session is still open."""
    with get_session() as session:
        try:
            account = get_paper_account(session)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        stmt = select(AccountEquitySnapshot).where(AccountEquitySnapshot.account_id == account.id)
        if date_from is not None:
            stmt = stmt.where(AccountEquitySnapshot.snapshot_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(AccountEquitySnapshot.snapshot_date <= date_to)
        stmt = stmt.order_by(AccountEquitySnapshot.snapshot_date.asc())
        rows = list(session.scalars(stmt))

    points = [
        EquityCurvePointResponse(
            snapshot_date=row.snapshot_date,
            equity=float(row.equity),
            cash=float(row.cash),
            unrealized_pnl=float(row.unrealized_pnl),
            margin_blocked=float(row.margin_blocked),
        )
        for row in rows
    ]

    today = date.today()
    already_snapshotted_today = points and points[-1].snapshot_date == today
    if not already_snapshotted_today and (date_to is None or date_to >= today):
        summary = await account_summary()
        points.append(
            EquityCurvePointResponse(
                snapshot_date=today,
                equity=summary.equity,
                cash=summary.cash,
                unrealized_pnl=summary.unrealized_pnl_total,
                margin_blocked=summary.margin_blocked,
            )
        )
    return points


_STATEMENT_FIELDNAMES = [
    "executed_at",
    "symbol",
    "instrument_type",
    "side",
    "filled_quantity",
    "fill_price",
    "slippage_bps",
    "strategy_id",
]


@router.get("/account/statement/export")
async def account_statement_export(
    export_format: Literal["csv", "ndjson"] = Query(default="csv", alias="format"),
) -> Response:
    """Reuses the exact CSV/NDJSON export pattern already built in src/api/routers/audit.py."""
    with get_session() as session:
        try:
            _account, trades = _account_and_trades(session)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    rows = [_to_response(t) for t in trades]

    if export_format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=_STATEMENT_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "executed_at": row.executed_at.isoformat(),
                    "symbol": row.symbol,
                    "instrument_type": row.instrument_type,
                    "side": row.side,
                    "filled_quantity": row.filled_quantity,
                    "fill_price": row.fill_price,
                    "slippage_bps": row.slippage_bps,
                    "strategy_id": row.strategy_id,
                }
            )
        return Response(content=buffer.getvalue(), media_type="text/csv")

    ndjson_body = "\n".join(row.model_dump_json() for row in rows)
    return Response(content=ndjson_body, media_type="application/x-ndjson")
