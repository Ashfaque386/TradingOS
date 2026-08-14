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

REL-055: `POST /orders` / `DELETE /orders/{order_id}` (API-054/055) close the real gap where a
human could never manually place or cancel an order through this API -- Paper already had this
for real via `POST /api/v1/paper-trading/execute` (API-111, `execute_paper_trade()`), so this
only needed building for Live. `account_scope="Live"` routes through the exact same real,
hardcoded gates the automated `LiveExecutionPipeline` already uses -- `kill_switch_service.
is_tripped()`, then `compliance_pre_trade_check()` (src/engine/live/execution_pipeline.py),
reused verbatim, no compliance logic duplicated here -- before ever calling the real
`broker.place_order()`/`cancel_order()`. `account_scope="Paper"` is a thin delegation to the
same `execute_paper_trade()` API-111 already calls, not a second implementation of paper fills.
`confirm_live_order=True` is a required, explicit safety latch on top of picking
`account_scope="Live"` -- this is the first endpoint in the project that can move real money on a
human's direct request, not through the AI pipeline or the paper-trading simulator.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import require_role
from src.brokers.base import OrderRequest as BrokerOrderRequest
from src.brokers.base import Side
from src.brokers.factory import NoBrokerConfigured, build_broker
from src.core.audit import write_audit_entry
from src.core.db import get_session
from src.core.security import ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER, ROLE_SYSTEM_ADMINISTRATOR
from src.engine.live.execution_pipeline import (
    RiskRejected,
    TradeSignal,
    compliance_pre_trade_check,
)
from src.engine.paper_trading.execution_service import NoLiquidityError, execute_paper_trade
from src.engine.paper_trading.paper_account import get_paper_account
from src.engine.paper_trading.position_accounting import replay_ledger
from src.engine.risk import kill_switch_service
from src.memory.redis_client import get_redis_client, publish_order_event
from src.models.account import Account
from src.models.paper_trading import PaperTrade
from src.models.strategy import Strategy
from src.models.trading import Order, Trade
from src.models.user import User
from src.observability.metrics import ORDER_EXECUTION_LATENCY_SECONDS

router = APIRouter(prefix="/api/v1", tags=["orders"])

# Same weight/role set as strategies.py's own _can_trigger_backtest -- placing or cancelling a
# real order is at least an equivalent-weight operational action.
_can_place_order = require_role(
    ROLE_SYSTEM_ADMINISTRATOR, ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER, audit_denials=True
)


def _publish_order_event(event: dict[str, Any]) -> None:
    """REL-061 (API-093): a real, best-effort publish to the live order-status stream (relayed
    verbatim by `GET /stream/orders`, src/api/routers/streams.py) -- a fresh Redis connection per
    call, matching this codebase's own established per-use-connection convention rather than a
    long-lived global client. A Redis hiccup must never block a real order placement/cancellation
    (the actual broker call and DB write already succeeded by the time this fires), so publish
    failures are swallowed, not raised."""
    try:
        client = get_redis_client()
        try:
            publish_order_event(client, json.dumps(event))
        finally:
            client.close()
    except Exception:  # noqa: BLE001 -- a display-feed publish failure must never fail the order
        pass


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


class OrderDetailResponse(OrderResponse):
    """API-056, adapted from the SRS's own "Order detail incl. broker ack and fills" wording --
    `broker_order_id`/`acknowledged_at` already on `OrderResponse` cover the broker ack; `fills`
    adds the real `Trade` rows this order produced (a Live order can fill in more than one Trade
    on a partial execution), read fresh from DB-009 rather than duplicating fill logic here."""

    broker_order_id: str | None
    fills: list[TradeResponse]


@router.get("/orders/{order_id}", response_model=OrderDetailResponse)
def get_order(order_id: uuid.UUID) -> OrderDetailResponse:
    """Registered after the /orders/execution-latency literal-path route above (and before
    POST /orders further below) -- FastAPI matches routes in registration order, so this dynamic
    {order_id} path must never come before a literal /orders/... path or it would shadow it (a
    request for /orders/execution-latency would otherwise bind order_id="execution-latency" and
    422 on UUID parsing instead of reaching the real endpoint)."""
    with get_session() as session:
        order = session.get(Order, order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Unknown order_id")
        fills = session.scalars(
            select(Trade).where(Trade.order_id == order_id).order_by(Trade.executed_at)
        )
        return OrderDetailResponse(
            **_order_to_response(order).model_dump(),
            broker_order_id=order.broker_order_id,
            fills=[_trade_to_response(t) for t in fills],
        )


def _get_or_create_live_account(session: Session, user_id: uuid.UUID) -> Account:
    """No Live Account DB row has ever existed in this system -- Live dashboard/portfolio reads
    have always gone straight to the broker API, never a DB row (unlike the seeded Paper
    account, see get_paper_account()). Order.account_id is a required FK, so the first real
    manual Live order ever placed lazily creates one, owned by whichever user placed it -- every
    later Live order reuses this same row (matches this codebase's own established
    lazily-self-heal pattern, e.g. the Vault Transit key recreated on boot). broker="LIVE" is a
    synthetic marker, the same convention get_paper_account() itself already uses (broker=
    "PAPER" is not a real broker name either) -- real capital always comes from the broker's own
    reported margin, not this row's capital_allocated column, which stays 0 as an honest
    placeholder, never a fabricated figure."""
    account = session.scalars(
        select(Account).where(Account.broker == "LIVE", Account.account_type == "Live")
    ).first()
    if account is not None:
        return account
    # REL-064: a new Account row needs a real tenant_id (NOT NULL) -- inherited from the
    # placing user's own tenant, not the global default, since a Live account is genuinely
    # this specific user's, unlike the one shared seeded Paper account.
    user = session.get(User, user_id)
    assert user is not None
    account = Account(
        user_id=user_id,
        tenant_id=user.tenant_id,
        broker="LIVE",
        account_type="Live",
        capital_allocated=0,
    )
    session.add(account)
    session.flush()
    return account


class PlaceOrderRequest(BaseModel):
    strategy_id: uuid.UUID
    symbol: str
    side: Side
    quantity: int = Field(gt=0)
    order_type: Literal["MARKET", "LIMIT"] = "MARKET"
    limit_price: float | None = None
    account_scope: Literal["Paper", "Live"]
    # Required True whenever account_scope == "Live" -- an explicit safety latch distinct from
    # the enum choice alone, since this is the first endpoint in the project that can move real
    # money on a direct human request rather than through the AI pipeline or paper simulator.
    confirm_live_order: bool = False


class PlaceOrderResponse(BaseModel):
    """Deliberately covers both scopes rather than forcing one shape on the other -- Live orders
    persist to `Order` (trading.py, DB-008) exactly like the automated pipeline; Paper orders
    delegate to the same `execute_paper_trade()` API-111 already calls, persisting to
    `PaperTrade` (paper_trading.py), a genuinely different table with a genuinely different
    shape -- not a second implementation of paper fills to keep the two response shapes
    artificially identical."""

    account_scope: Literal["Paper", "Live"]
    symbol: str
    side: str
    quantity: int
    status: str
    executed_at: datetime
    order_id: uuid.UUID | None = None  # Order.id -- Live only
    broker_order_id: str | None = None  # Live only
    paper_trade_id: uuid.UUID | None = None  # PaperTrade.id -- Paper only
    fill_price: float | None = None  # Paper only, real slippage-simulated fill price


@router.post("/orders", response_model=PlaceOrderResponse, status_code=201)
async def place_order(
    body: PlaceOrderRequest, user: User = Depends(_can_place_order)
) -> PlaceOrderResponse:
    if body.account_scope == "Live" and not body.confirm_live_order:
        raise HTTPException(
            status_code=400,
            detail="account_scope=Live requires confirm_live_order=true -- this places a real "
            "order against a real broker for real money.",
        )
    if kill_switch_service.is_tripped():
        raise HTTPException(
            status_code=423, detail="Kill switch is tripped -- no orders can be placed"
        )

    with get_session() as session:
        strategy = session.get(Strategy, body.strategy_id)
        if strategy is None:
            raise HTTPException(status_code=404, detail="Unknown strategy_id")

        signal = TradeSignal(
            symbol=body.symbol,
            side=body.side,
            quantity=body.quantity,
            order_type=body.order_type,
            limit_price=body.limit_price,
        )
        try:
            compliance_pre_trade_check(signal)
        except RiskRejected as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

        if body.account_scope == "Paper":
            try:
                broker = build_broker()
            except NoBrokerConfigured as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            account_id = str(get_paper_account(session).id)
            try:
                trade = await execute_paper_trade(
                    broker,
                    symbol=body.symbol,
                    side=body.side,
                    quantity=body.quantity,
                    account_id=account_id,
                    strategy_id=str(strategy.id),
                )
            except NoLiquidityError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            write_audit_entry(
                session,
                actor_type="Human",
                actor_id=str(user.id),
                action="ORDER_PLACED_PAPER",
                entity_type="PaperTrade",
                entity_id=trade.id,
                after_state={
                    "symbol": trade.symbol,
                    "side": trade.side,
                    "quantity": trade.filled_quantity,
                },
            )
            session.commit()
            _publish_order_event(
                {
                    "account_scope": "Paper",
                    "paper_trade_id": str(trade.id),
                    "symbol": trade.symbol,
                    "side": trade.side,
                    "quantity": trade.filled_quantity,
                    "status": "FILLED",
                    "ts": trade.executed_at.isoformat(),
                }
            )
            return PlaceOrderResponse(
                account_scope="Paper",
                symbol=trade.symbol,
                side=trade.side,
                quantity=trade.filled_quantity,
                status="FILLED",
                executed_at=trade.executed_at,
                paper_trade_id=trade.id,
                fill_price=float(trade.fill_price),
            )

        # Live
        try:
            broker = build_broker()
        except NoBrokerConfigured as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        account = _get_or_create_live_account(session, user.id)

        broker_order = BrokerOrderRequest(
            symbol=body.symbol,
            side=body.side,
            order_type=body.order_type,
            quantity=body.quantity,
            limit_price=body.limit_price,
        )
        response = await broker.place_order(broker_order)

        order = Order(
            account_id=account.id,
            tenant_id=account.tenant_id,
            strategy_id=strategy.id,
            broker_order_id=response.broker_order_id,
            symbol=response.symbol,
            side=response.side,
            order_type=response.order_type,
            quantity=response.quantity,
            limit_price=body.limit_price,
            status=response.status,
            requested_at=datetime.now(UTC),
            acknowledged_at=datetime.now(UTC),
        )
        session.add(order)
        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=str(user.id),
            action="ORDER_PLACED_LIVE",
            entity_type="Order",
            after_state={
                "symbol": order.symbol,
                "side": order.side,
                "quantity": order.quantity,
                "broker_order_id": order.broker_order_id,
            },
        )
        session.commit()
        session.refresh(order)
        _publish_order_event(
            {
                "account_scope": "Live",
                "order_id": str(order.id),
                "broker_order_id": order.broker_order_id,
                "symbol": order.symbol,
                "side": order.side,
                "quantity": order.quantity,
                "status": order.status,
                "ts": order.requested_at.isoformat(),
            }
        )
        return PlaceOrderResponse(
            account_scope="Live",
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            status=order.status,
            executed_at=order.requested_at,
            order_id=order.id,
            broker_order_id=order.broker_order_id,
        )


@router.delete("/orders/{order_id}", response_model=OrderResponse)
async def cancel_order(
    order_id: uuid.UUID, user: User = Depends(_can_place_order)
) -> OrderResponse:
    with get_session() as session:
        order = session.get(Order, order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Unknown order_id")
        if order.broker_order_id is None:
            raise HTTPException(
                status_code=400,
                detail="This order has no broker_order_id -- Paper orders "
                "(POST /api/v1/paper-trading/execute) fill instantly and cannot be cancelled.",
            )
        try:
            broker = build_broker()
        except NoBrokerConfigured as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        response = await broker.cancel_order(order.broker_order_id)
        order.status = response.status
        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=str(user.id),
            action="ORDER_CANCELLED",
            entity_type="Order",
            entity_id=order.id,
            after_state={"status": order.status},
        )
        session.commit()
        session.refresh(order)
        _publish_order_event(
            {
                "account_scope": "Live",
                "order_id": str(order.id),
                "broker_order_id": order.broker_order_id,
                "symbol": order.symbol,
                "side": order.side,
                "quantity": order.quantity,
                "status": order.status,
                "ts": datetime.now(UTC).isoformat(),
            }
        )
        return _order_to_response(order)


class ClosePositionRequest(BaseModel):
    # Closing a position is always in the context of one strategy's own book, matching this
    # system's per-strategy attribution philosophy everywhere else (Order.strategy_id is
    # required too) -- even though a real broker's own position is symbol-level, not
    # strategy-level; there's no other real signal to attribute the closing order to.
    strategy_id: uuid.UUID
    account_scope: Literal["Paper", "Live"]
    confirm_live_order: bool = False


@router.post("/positions/{symbol}/close", response_model=PlaceOrderResponse, status_code=201)
async def close_position(
    symbol: str, body: ClosePositionRequest, user: User = Depends(_can_place_order)
) -> PlaceOrderResponse:
    """API-058, adapted from the SRS's literal `{position_id}` path -- real positions come from
    `broker.get_positions()` (Live, symbol-keyed) or a fresh ledger replay (Paper), neither of
    which has a DB row with an id to path on, unlike the SRS's assumption. Resolves the real
    current net_quantity for `symbol`, then places the exact opposite-side order through
    `place_order` above (not a second implementation) -- a close is just an order in the closing
    direction."""
    with get_session() as session:
        strategy = session.get(Strategy, body.strategy_id)
        if strategy is None:
            raise HTTPException(status_code=404, detail="Unknown strategy_id")

        if body.account_scope == "Paper":
            trades = list(
                session.scalars(
                    select(PaperTrade)
                    .where(PaperTrade.strategy_id == body.strategy_id)
                    .order_by(PaperTrade.executed_at)
                )
            )
            positions, _ = replay_ledger(trades)
            pos = positions.get(symbol)
            if pos is None or pos.net_quantity == 0:
                raise HTTPException(
                    status_code=404,
                    detail=f"No open Paper position for {symbol} under this strategy",
                )
            net_quantity = pos.net_quantity
        else:
            try:
                broker = build_broker()
            except NoBrokerConfigured as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            try:
                live_positions = await broker.get_positions()
            except httpx.HTTPStatusError as exc:
                raise HTTPException(
                    status_code=502, detail=f"Broker positions request failed: {exc}"
                ) from exc
            match = next((p for p in live_positions if p.symbol == symbol), None)
            if match is None or match.net_quantity == 0:
                raise HTTPException(status_code=404, detail=f"No open Live position for {symbol}")
            net_quantity = match.net_quantity

    close_side: Side = "SELL" if net_quantity > 0 else "BUY"
    close_request = PlaceOrderRequest(
        strategy_id=body.strategy_id,
        symbol=symbol,
        side=close_side,
        quantity=abs(net_quantity),
        order_type="MARKET",
        account_scope=body.account_scope,
        confirm_live_order=body.confirm_live_order,
    )
    return await place_order(close_request, user)
