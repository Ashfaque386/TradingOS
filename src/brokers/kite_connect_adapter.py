"""Zerodha Kite Connect broker adapter (Phase 4 Epic E4.1), per
Phase_6_Trading_Engine_Design.md §6: "Zerodha Implementation (KiteConnectAdapter): Primary
executor."

Endpoint paths, request/response fields, and the auth/order-status vocabulary below were
confirmed directly against Kite Connect v3's own documentation (https://kite.trade/docs/connect/v3/),
including live curl examples quoted verbatim from the orders page, not guessed.

SAFETY -- read before touching this file: unlike UpstoxAdapter, Kite Connect has **no sandbox
mode**. Every credential configured for it is real production access to a real trading account.
`place_order`/`modify_order`/`cancel_order` must never be exercised against the live API from
automated tests -- they are covered only by mocked HTTP unit tests
(tests/unit/test_kite_connect_adapter.py). Only read-only methods (get_margin/get_positions/
get_order_book) are verified against the real API, in
tests/integration/test_kite_connect_live.py.
"""

from typing import Any

import httpx

from src.brokers.base import (
    BrokerAdapter,
    DepthLevel,
    Margin,
    OrderRequest,
    OrderResponse,
    OrderStatus,
    OrderType,
    Position,
    Quote,
    Side,
)

KITE_BASE_URL = "https://api.kite.trade"
KITE_VARIETY = "regular"  # this adapter only supports regular orders (not amo/co/iceberg/auction)

_PRODUCT_CODE = {"INTRADAY": "MIS", "DELIVERY": "CNC"}

# Kite's order status vocabulary, mapped onto our own DB-008 ORDERS.status values
# (Phase_11_Database_Design.md). Reconstructed from Kite Connect's public docs, not exhaustively
# verified against a live order lifecycle (Kite has no sandbox to safely generate every status
# in) -- an unmapped status raises rather than silently mis-recording order state.
_STATUS_MAP: dict[str, OrderStatus] = {
    "complete": "FILLED",
    "open": "OPEN",
    "cancelled": "CANCELLED",
    "rejected": "REJECTED",
    "put order req received": "PENDING",
    "validation pending": "PENDING",
    "open pending": "PENDING",
    "amo req received": "PENDING",
    "modify validation pending": "OPEN",
    "modify pending": "OPEN",
    "modified": "OPEN",
    "trigger pending": "OPEN",
    "cancel pending": "OPEN",
}


class KiteOrderStatusError(ValueError):
    """Raised when Kite returns an order status string not in `_STATUS_MAP` -- surfaced loudly
    rather than guessed at, since silently mis-mapping order state in a trading system is worse
    than failing loudly."""


class KiteConnectAdapter(BrokerAdapter):
    def __init__(self, *, api_key: str, access_token: str, timeout: float = 10.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=KITE_BASE_URL,
            headers={
                "Authorization": f"token {api_key}:{access_token}",
                "X-Kite-Version": "3",
                "Accept": "application/json",
            },
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "KiteConnectAdapter":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # --- BrokerAdapter interface -------------------------------------------------------

    def build_order_payload(self, order: OrderRequest) -> dict[str, Any]:
        """The exact real request body place_order() sends -- pulled out as its own pure,
        no-I/O method so Shadow Mode (Phase 4 E4.4, src/brokers/shadow_mode.py) can validate a
        real Kite order's shape (correct field names, a resolvable product code, etc.) without
        ever calling the network. Kite Connect has no sandbox at all, so this local construction
        is the only safe "would this be a well-formed order" check available for it."""
        payload: dict[str, Any] = {
            "tradingsymbol": order.symbol,
            "exchange": "NSE",
            "transaction_type": order.side,
            "order_type": order.order_type,
            "quantity": order.quantity,
            "product": _PRODUCT_CODE[order.product],
            "validity": order.validity,
        }
        if order.limit_price is not None:
            payload["price"] = order.limit_price
        if order.trigger_price is not None:
            payload["trigger_price"] = order.trigger_price
        if order.tag:
            payload["tag"] = order.tag
        return payload

    async def place_order(self, order: OrderRequest) -> OrderResponse:
        payload = self.build_order_payload(order)
        response = await self._client.post(f"/orders/{KITE_VARIETY}", data=payload)
        response.raise_for_status()
        broker_order_id: str = response.json()["data"]["order_id"]

        return OrderResponse(
            broker_order_id=broker_order_id,
            status="PENDING",  # place response has no status; caller polls get_order_book
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            quantity=order.quantity,
            limit_price=order.limit_price,
            raw=response.json(),
        )

    async def modify_order(
        self,
        broker_order_id: str,
        *,
        quantity: int | None = None,
        order_type: OrderType | None = None,
        limit_price: float | None = None,
        trigger_price: float | None = None,
    ) -> OrderResponse:
        payload: dict[str, Any] = {}
        if quantity is not None:
            payload["quantity"] = quantity
        if order_type is not None:
            payload["order_type"] = order_type
        if limit_price is not None:
            payload["price"] = limit_price
        if trigger_price is not None:
            payload["trigger_price"] = trigger_price

        response = await self._client.put(f"/orders/{KITE_VARIETY}/{broker_order_id}", data=payload)
        response.raise_for_status()

        # The modify response only echoes back {"data": {"order_id": ...}}, not the order's
        # full current state -- re-fetch the order book for an accurate OrderResponse rather
        # than assembling one from what we merely requested (a modify can be partially applied
        # or race a fill).
        return await self._fetch_single_order(broker_order_id)

    async def cancel_order(self, broker_order_id: str) -> OrderResponse:
        response = await self._client.delete(f"/orders/{KITE_VARIETY}/{broker_order_id}")
        response.raise_for_status()
        # Same reasoning as modify_order: confirm actual post-cancel state, don't assume success
        # means "CANCELLED" (the order may have already filled before the cancel landed).
        return await self._fetch_single_order(broker_order_id)

    async def get_order_book(self) -> list[OrderResponse]:
        response = await self._client.get("/orders")
        response.raise_for_status()
        return [self._parse_order(raw) for raw in response.json()["data"]]

    async def get_margin(self) -> Margin:
        response = await self._client.get("/user/margins/equity")
        response.raise_for_status()
        data = response.json()["data"]
        return Margin(
            available_margin=data["net"], used_margin=data["utilised"]["debits"], raw=data
        )

    async def get_positions(self) -> list[Position]:
        response = await self._client.get("/portfolio/positions")
        response.raise_for_status()
        net_positions = response.json()["data"]["net"]
        return [
            Position(
                symbol=raw["tradingsymbol"],
                net_quantity=raw["quantity"],
                average_price=raw.get("average_price"),
                last_price=raw.get("last_price"),
                unrealized_pnl=raw.get("unrealised", 0.0),
                realized_pnl=raw.get("realised", 0.0),
            )
            for raw in net_positions
        ]

    async def get_quote(self, symbol: str) -> Quote:
        instrument = f"NSE:{symbol}"
        response = await self._client.get("/quote", params={"i": instrument})
        response.raise_for_status()
        data = response.json()["data"][instrument]
        depth = data.get("depth", {})
        return Quote(
            symbol=symbol,
            last_price=data["last_price"],
            buy_depth=[DepthLevel(**level) for level in depth.get("buy", [])],
            sell_depth=[DepthLevel(**level) for level in depth.get("sell", [])],
        )

    # --- internals -------------------------------------------------------------------

    async def _fetch_single_order(self, broker_order_id: str) -> OrderResponse:
        for order in await self.get_order_book():
            if order.broker_order_id == broker_order_id:
                return order
        raise ValueError(f"Order {broker_order_id!r} not found in Kite order book")

    def _parse_order(self, raw: dict[str, Any]) -> OrderResponse:
        status_str = str(raw["status"]).lower()
        if status_str not in _STATUS_MAP:
            raise KiteOrderStatusError(
                f"Unmapped Kite order status {raw['status']!r} for order {raw.get('order_id')}"
            )
        status = _STATUS_MAP[status_str]
        quantity = raw["quantity"]
        filled_quantity = raw.get("filled_quantity", 0)
        # Kite has no distinct "partially filled" status string -- a still-open order with some
        # (but not all) quantity filled is functionally partially filled.
        if status == "OPEN" and 0 < filled_quantity < quantity:
            status = "PARTIALLY_FILLED"

        side: Side = raw["transaction_type"]
        order_type: OrderType = raw["order_type"]
        return OrderResponse(
            broker_order_id=raw["order_id"],
            status=status,
            symbol=raw["tradingsymbol"],
            side=side,
            order_type=order_type,
            quantity=quantity,
            filled_quantity=filled_quantity,
            average_price=raw.get("average_price") or None,
            limit_price=raw.get("price") or None,
            rejection_reason=raw.get("status_message") or None,
            raw=raw,
        )
