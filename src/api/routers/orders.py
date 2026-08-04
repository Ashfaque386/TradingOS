"""Live order/trade history endpoints (REL-018 E18.1) -- the one dashboard gap the 2026-08-01
audit found that wasn't just a missing UI: `ORDERS`/`TRADES` (DB-008/009) have been real Postgres
tables since Phase 1, but no endpoint anywhere ever listed them for real (live) trading, unlike
Paper Trading's own list endpoints (`src/api/routers/paper_trading.py`), which this router
deliberately mirrors -- same shape (a single optional `strategy_id` filter, no pagination), same
"GET stays open, Any role" convention this codebase already established for read-only trade data.

`execution_latency` below mirrors `src/api/routers/audit.py`'s `agent_run_durations` pattern: a
thin wrapper over the real, already-scraped `tradingos_order_execution_latency_seconds` Histogram
(src/observability/metrics.py) -- reads the metric's own real `_count`/`_sum` samples, never a
separate DB query, so this can never drift from what Grafana itself shows. The histogram carries
no labels (a single process-wide latency distribution, not broken out per strategy/symbol), so
this is one overall summary, not a per-strategy breakdown.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from src.core.db import get_session
from src.models.trading import Order, Trade
from src.observability.metrics import ORDER_EXECUTION_LATENCY_SECONDS

router = APIRouter(prefix="/api/v1", tags=["orders"])


class OrderResponse(BaseModel):
    id: uuid.UUID
    strategy_id: uuid.UUID
    symbol: str
    side: str
    order_type: str
    quantity: int
    limit_price: float | None
    status: str
    requested_at: datetime
    acknowledged_at: datetime | None
    latency_ms: int | None
    rejection_reason: str | None


def _order_to_response(order: Order) -> OrderResponse:
    return OrderResponse(
        id=order.id,
        strategy_id=order.strategy_id,
        symbol=order.symbol,
        side=order.side,
        order_type=order.order_type,
        quantity=order.quantity,
        limit_price=float(order.limit_price) if order.limit_price is not None else None,
        status=order.status,
        requested_at=order.requested_at,
        acknowledged_at=order.acknowledged_at,
        latency_ms=order.latency_ms,
        rejection_reason=order.rejection_reason,
    )


@router.get("/orders", response_model=list[OrderResponse])
def list_orders(strategy_id: uuid.UUID | None = None) -> list[OrderResponse]:
    with get_session() as session:
        query = select(Order).order_by(Order.requested_at.desc())
        if strategy_id is not None:
            query = query.where(Order.strategy_id == strategy_id)
        orders = session.scalars(query)
        return [_order_to_response(o) for o in orders]


class TradeResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    strategy_id: uuid.UUID
    symbol: str
    side: str
    price: float
    quantity: int
    brokerage: float
    stt: float
    gst: float
    net_pnl: float | None
    executed_at: datetime


def _trade_to_response(trade: Trade) -> TradeResponse:
    return TradeResponse(
        id=trade.id,
        order_id=trade.order_id,
        strategy_id=trade.strategy_id,
        symbol=trade.symbol,
        side=trade.side,
        price=float(trade.price),
        quantity=trade.quantity,
        brokerage=float(trade.brokerage),
        stt=float(trade.stt),
        gst=float(trade.gst),
        net_pnl=float(trade.net_pnl) if trade.net_pnl is not None else None,
        executed_at=trade.executed_at,
    )


@router.get("/trades", response_model=list[TradeResponse])
def list_trades(strategy_id: uuid.UUID | None = None) -> list[TradeResponse]:
    with get_session() as session:
        query = select(Trade).order_by(Trade.executed_at.desc())
        if strategy_id is not None:
            query = query.where(Trade.strategy_id == strategy_id)
        trades = session.scalars(query)
        return [_trade_to_response(t) for t in trades]


class ExecutionLatencySummary(BaseModel):
    sample_count: int
    total_seconds: float
    avg_ms: float | None


@router.get("/orders/execution-latency", response_model=ExecutionLatencySummary)
def execution_latency() -> ExecutionLatencySummary:
    count = 0.0
    total = 0.0
    for metric_family in ORDER_EXECUTION_LATENCY_SECONDS.collect():
        for sample in metric_family.samples:
            if sample.name.endswith("_count"):
                count = sample.value
            elif sample.name.endswith("_sum"):
                total = sample.value
    return ExecutionLatencySummary(
        sample_count=int(count),
        total_seconds=total,
        avg_ms=(total / count * 1000) if count else None,
    )
