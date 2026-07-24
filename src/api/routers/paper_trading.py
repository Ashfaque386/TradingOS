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
"""

import uuid
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from src.brokers.base import Side
from src.brokers.factory import NoBrokerConfigured, build_broker
from src.core.db import get_session
from src.engine.paper_trading.execution_service import NoLiquidityError, execute_paper_trade
from src.engine.paper_trading.position_accounting import replay_ledger
from src.models.paper_trading import PaperTrade

router = APIRouter(prefix="/api/v1/paper-trading", tags=["paper-trading"])


class ExecuteRequest(BaseModel):
    symbol: str
    side: Side
    quantity: int
    strategy_id: uuid.UUID | None = None


class PaperTradeResponse(BaseModel):
    id: uuid.UUID
    strategy_id: uuid.UUID | None
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
        strategy_id=trade.strategy_id,
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
async def execute(body: ExecuteRequest) -> PaperTradeResponse:
    try:
        broker = build_broker()
    except NoBrokerConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        trade = await execute_paper_trade(
            broker,
            symbol=body.symbol,
            side=body.side,
            quantity=body.quantity,
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
