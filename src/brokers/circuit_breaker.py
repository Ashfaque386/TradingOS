"""Circuit breaker + automated failover for broker order routing (Phase 4 Epic E4.1), per
Phase_6_Trading_Engine_Design.md §6:

  "Resiliency: Implements circuit breakers. If Zerodha returns 5XX errors consecutively, the
  execution engine queues the orders and alerts the human administrator, preventing duplicate
  order placements during API timeouts."

Written broker-agnostically (a `primary`/`fallback` pair of `BrokerAdapter`, not hardcoded to
Zerodha/Upstox) since only `UpstoxAdapter` exists so far -- `KiteConnectAdapter` (Zerodha) slots
in as `primary` once it's implemented, with `UpstoxAdapter` as `fallback`, matching Phase_6 §6's
"Zerodha: Primary executor. Upstox: Secondary executor/fallback."

Only `place_order` failures affect circuit state: that's the one operation where a retry after
an ambiguous timeout risks a duplicate live order. `modify_order`/`cancel_order`/read methods
always target `primary` directly and simply propagate its errors -- an existing order lives on
whichever broker placed it, and this breaker has no order->broker ownership map (that belongs to
the Execution Agent's order-tracking table, Phase 4 E4.2).
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal

import httpx

from src.brokers.base import (
    BrokerAdapter,
    Margin,
    OptionChain,
    OrderRequest,
    OrderResponse,
    OrderType,
    Position,
    Quote,
)

CircuitState = Literal["CLOSED", "OPEN", "HALF_OPEN"]


@dataclass(frozen=True)
class QueuedOrder:
    order: OrderRequest
    queued_at: datetime
    reason: str


class AdminAlert(Exception):
    """Raised whenever the circuit breaker needs a human's attention: the primary broker is
    down and there's no fallback able to take the order. Callers are expected to catch this and
    route it to a real alerting channel (PagerDuty/Slack, Phase 4 E4.4) -- it is not swallowed
    here, since a queued-and-unplaced order is exactly the kind of thing that must not go
    silently unnoticed."""


@dataclass
class BrokerCircuitBreaker(BrokerAdapter):
    primary: BrokerAdapter
    fallback: BrokerAdapter | None = None
    failure_threshold: int = 3  # "consecutive 5XX errors" per Phase_6 §6
    cooldown: timedelta = timedelta(minutes=1)

    _state: CircuitState = field(default="CLOSED", init=False)
    _consecutive_failures: int = field(default=0, init=False)
    _opened_at: datetime | None = field(default=None, init=False)
    queued_orders: list[QueuedOrder] = field(default_factory=list, init=False)
    alerts: list[str] = field(default_factory=list, init=False)

    @property
    def state(self) -> CircuitState:
        return self._state

    # --- BrokerAdapter interface -------------------------------------------------------

    async def place_order(self, order: OrderRequest) -> OrderResponse:
        self._maybe_half_open()

        if self._state == "OPEN":
            return await self._route_to_fallback_or_queue(order, reason="circuit open")

        try:
            response = await self.primary.place_order(order)
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            if not self._is_server_error(exc):
                raise
            if self._state == "HALF_OPEN":
                # A probe failure during recovery testing reopens immediately -- it doesn't
                # need to re-accumulate `failure_threshold` failures from scratch.
                self._open_circuit()
                return await self._route_to_fallback_or_queue(
                    order, reason="half-open probe failed"
                )
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.failure_threshold:
                self._open_circuit()
                return await self._route_to_fallback_or_queue(
                    order, reason=f"{self._consecutive_failures} consecutive 5XX errors"
                )
            raise
        else:
            self._consecutive_failures = 0
            self._state = "CLOSED"
            return response

    async def modify_order(
        self,
        broker_order_id: str,
        *,
        quantity: int | None = None,
        order_type: OrderType | None = None,
        limit_price: float | None = None,
        trigger_price: float | None = None,
    ) -> OrderResponse:
        return await self.primary.modify_order(
            broker_order_id,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            trigger_price=trigger_price,
        )

    async def cancel_order(self, broker_order_id: str) -> OrderResponse:
        return await self.primary.cancel_order(broker_order_id)

    async def get_order_book(self) -> list[OrderResponse]:
        return await self.primary.get_order_book()

    async def get_margin(self) -> Margin:
        return await self.primary.get_margin()

    async def get_positions(self) -> list[Position]:
        return await self.primary.get_positions()

    async def get_quote(self, symbol: str) -> Quote:
        return await self.primary.get_quote(symbol)

    async def get_option_chain(self, underlying: str, expiry: date) -> OptionChain:
        return await self.primary.get_option_chain(underlying, expiry)

    # --- circuit breaker internals ------------------------------------------------------

    @staticmethod
    def _is_server_error(exc: Exception) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code >= 500
        return isinstance(exc, httpx.TransportError)  # connection errors, timeouts

    def _open_circuit(self) -> None:
        self._state = "OPEN"
        self._opened_at = datetime.now(UTC)

    def _maybe_half_open(self) -> None:
        if (
            self._state == "OPEN"
            and self._opened_at is not None
            and datetime.now(UTC) - self._opened_at >= self.cooldown
        ):
            self._state = "HALF_OPEN"

    async def _route_to_fallback_or_queue(
        self, order: OrderRequest, *, reason: str
    ) -> OrderResponse:
        if self.fallback is not None:
            self._alert(f"Circuit OPEN ({reason}) -- failing over order for {order.symbol}.")
            return await self.fallback.place_order(order)

        self.queued_orders.append(
            QueuedOrder(order=order, queued_at=datetime.now(UTC), reason=reason)
        )
        self._alert(
            f"Order for {order.symbol} queued ({reason}) -- primary down, no fallback available."
        )
        raise AdminAlert(
            f"Circuit breaker OPEN ({reason}) and no fallback broker configured -- order for "
            f"{order.symbol} queued for manual review, not placed."
        )

    def _alert(self, message: str) -> None:
        # In-process alert log for now; Phase 4 E4.4 wires this to PagerDuty/Slack.
        self.alerts.append(message)
