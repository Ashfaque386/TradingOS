"""Broker abstraction layer (Phase 4 Epic E4.1), per Phase_6_Trading_Engine_Design.md §6:

  "A strict abstraction layer decoupling TradingOS from specific Indian broker APIs. Interface
  (BrokerAdapter): Defines standard methods: place_order(), modify_order(), cancel_order(),
  get_order_book(), get_margin(), get_positions()."

Field names on the request/response models mirror DB-008 ORDERS and DB-010 PORTFOLIO_POSITIONS
(Phase_11_Database_Design.md) so a placed order or fetched position can be persisted without a
translation layer. Broker-specific vocabulary (e.g. Upstox's `product`/`validity` codes) is
mapped inside each adapter, not leaked into this abstraction.

All methods are async: the live execution pipeline (Phase 4 E4.2) has a <50ms tick-to-order
latency budget (NFR-02), so broker HTTP calls must not block the event loop.
"""

from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Side = Literal["BUY", "SELL"]
OrderType = Literal["MARKET", "LIMIT", "SL", "SL-M"]
OrderStatus = Literal["PENDING", "OPEN", "PARTIALLY_FILLED", "FILLED", "CANCELLED", "REJECTED"]
ProductType = Literal["INTRADAY", "DELIVERY"]
Validity = Literal["DAY", "IOC"]


class BrokerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OrderRequest(BrokerModel):
    symbol: str
    side: Side
    order_type: OrderType
    quantity: int = Field(gt=0)
    product: ProductType = "INTRADAY"
    limit_price: float | None = None  # required for LIMIT/SL
    trigger_price: float | None = None  # required for SL/SL-M
    validity: Validity = "DAY"
    tag: str | None = Field(default=None, max_length=40)


class OrderResponse(BrokerModel):
    broker_order_id: str
    status: OrderStatus
    symbol: str
    side: Side
    order_type: OrderType
    quantity: int
    filled_quantity: int = 0
    average_price: float | None = None
    limit_price: float | None = None
    rejection_reason: str | None = None
    raw: dict[str, object] = Field(default_factory=dict)  # full broker payload, for audit/debugging


class Position(BrokerModel):
    symbol: str
    net_quantity: int
    average_price: float | None = None
    last_price: float | None = None
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


class Margin(BrokerModel):
    available_margin: float
    used_margin: float
    raw: dict[str, object] = Field(default_factory=dict)


class DepthLevel(BrokerModel):
    price: float
    quantity: int
    orders: int


class Quote(BrokerModel):
    """Real Level-2 market depth (Phase 4 Epic E4.4, Paper Trading Engine per
    Phase_6_Trading_Engine_Design.md §5: "Applies aggressive slippage assumptions and partial
    fill probabilities based on real-time order book depth"). `buy_depth`/`sell_depth` are up to
    5 levels each, exactly what both Zerodha's `/quote` and Upstox's `/market-quote/quotes`
    return -- no deeper synthetic levels are fabricated beyond what the broker actually reports."""

    symbol: str
    last_price: float
    buy_depth: list[DepthLevel] = Field(default_factory=list)
    sell_depth: list[DepthLevel] = Field(default_factory=list)


class BrokerAdapter(ABC):
    """A concrete adapter (e.g. `UpstoxAdapter`) implements every method against one broker's
    real API. Callers (the Execution Agent, E4.2) depend only on this interface, never on a
    specific broker's SDK or response shape."""

    @abstractmethod
    async def place_order(self, order: OrderRequest) -> OrderResponse: ...

    @abstractmethod
    async def modify_order(
        self,
        broker_order_id: str,
        *,
        quantity: int | None = None,
        order_type: OrderType | None = None,
        limit_price: float | None = None,
        trigger_price: float | None = None,
    ) -> OrderResponse:
        """Fields left as `None` keep their originally-placed value."""
        ...

    @abstractmethod
    async def cancel_order(self, broker_order_id: str) -> OrderResponse: ...

    @abstractmethod
    async def get_order_book(self) -> list[OrderResponse]: ...

    @abstractmethod
    async def get_margin(self) -> Margin: ...

    @abstractmethod
    async def get_positions(self) -> list[Position]: ...

    @abstractmethod
    async def get_quote(self, symbol: str) -> Quote:
        """Real Level-2 market depth for one symbol (Phase 4 E4.4, Paper Trading Engine).
        Read-only market data -- no order is placed, no funds move -- so unlike
        place_order/modify_order/cancel_order this is safe to exercise against the real API
        even for adapters that route order placement to a broker's live production endpoint."""
        ...
