"""Shadow Mode (Phase 4 Epic E4.4), per Phase_9_Master_Implementation_Guide.md §4: "Before full
live trading, the Execution Engine will run in 'Shadow Mode' -- generating orders, pushing them
to the broker API, but using a custom 'Dry Run' header to validate API syntax and latency without
actually executing the trade."

That description assumes every broker supports a dry-run flag on its real order-placement API.
Neither Zerodha nor Upstox actually does -- confirmed by this project's own broker research this
session (see src/brokers/kite_connect_adapter.py and upstox_adapter.py's module docstrings) --
so this module treats the two brokers honestly differently rather than pretending a uniform
mechanism exists:

  - Upstox HAS a genuine sandbox (`api-sandbox.upstox.com`) that "closely emulates the real API
    with no risk" (Upstox's own docs). For Upstox, Shadow Mode really does push a real order to
    a real broker endpoint and get a real response -- it just happens to be the sandbox endpoint,
    which is exactly what a dry run should be.
  - Zerodha's Kite Connect has NO sandbox mode at all. A Kite order-placement call is always a
    real production call against real funds -- there is no dry-run header, no test flag, nothing
    to opt into. For Zerodha, "Shadow Mode" here means constructing the exact real request
    payload (KiteConnectAdapter.build_order_payload(), a pure, no-network method) and validating
    it locally, WITHOUT ever calling place_order. This validates syntax/shape, honestly, at the
    cost of not validating against the real live endpoint the way Upstox's path does -- there is
    no safer way to get closer to that on Zerodha specifically.

Every attempt is persisted to SHADOW_MODE_ATTEMPTS (src/models/shadow_mode.py) regardless of
outcome, so "5 consecutive days, zero broker API syntax errors" (the go-live gate this epic
serves) is a real, queryable fact once this has actually run for 5 real trading days -- not
something asserted without evidence.
"""

import time
from dataclasses import dataclass
from typing import Any, Literal

from src.brokers.base import BrokerAdapter, OrderRequest
from src.brokers.kite_connect_adapter import KiteConnectAdapter
from src.brokers.upstox_adapter import UpstoxAdapter

ShadowOutcome = Literal["Validated", "Error"]


@dataclass(frozen=True)
class ShadowAttemptResult:
    broker: str
    outcome: ShadowOutcome
    request_payload: dict[str, Any]
    error_detail: str | None
    latency_ms: float
    used_real_sandbox: bool


class UnsupportedBrokerError(ValueError):
    """Raised for a broker type Shadow Mode doesn't know how to handle -- fail loudly rather
    than silently defaulting to either the sandbox-call path or the local-only path, since
    picking the wrong one for an unknown adapter could mean an unintended real order."""


class ShadowModeAdapter:
    def __init__(self, broker: BrokerAdapter, *, broker_name: str) -> None:
        self._broker = broker
        self._broker_name = broker_name

    async def attempt_order(self, order: OrderRequest) -> ShadowAttemptResult:
        start = time.monotonic()

        if isinstance(self._broker, UpstoxAdapter):
            return await self._attempt_via_real_sandbox(order, start)
        if isinstance(self._broker, KiteConnectAdapter):
            return self._attempt_via_local_validation_only(order, start)
        raise UnsupportedBrokerError(
            f"Shadow Mode has no defined behavior for broker adapter type {type(self._broker).__name__}"
        )

    async def _attempt_via_real_sandbox(self, order: OrderRequest, start: float) -> ShadowAttemptResult:
        payload = {
            "quantity": order.quantity,
            "instrument_token": order.symbol,
            "order_type": order.order_type,
            "transaction_type": order.side,
            "product": order.product,
            "validity": order.validity,
        }
        try:
            await self._broker.place_order(order)  # real call, real sandbox -- no real funds
            return ShadowAttemptResult(
                broker=self._broker_name,
                outcome="Validated",
                request_payload=payload,
                error_detail=None,
                latency_ms=(time.monotonic() - start) * 1000,
                used_real_sandbox=True,
            )
        except Exception as exc:  # noqa: BLE001 - any failure here is exactly what Shadow Mode exists to catch
            return ShadowAttemptResult(
                broker=self._broker_name,
                outcome="Error",
                request_payload=payload,
                error_detail=str(exc),
                latency_ms=(time.monotonic() - start) * 1000,
                used_real_sandbox=True,
            )

    def _attempt_via_local_validation_only(
        self, order: OrderRequest, start: float
    ) -> ShadowAttemptResult:
        assert isinstance(self._broker, KiteConnectAdapter)  # narrows the type for build_order_payload
        try:
            payload = self._broker.build_order_payload(order)
            return ShadowAttemptResult(
                broker=self._broker_name,
                outcome="Validated",
                request_payload=payload,
                error_detail=None,
                latency_ms=(time.monotonic() - start) * 1000,
                used_real_sandbox=False,
            )
        except Exception as exc:  # noqa: BLE001 - e.g. an unmapped product code
            return ShadowAttemptResult(
                broker=self._broker_name,
                outcome="Error",
                request_payload=order.model_dump(),
                error_detail=str(exc),
                latency_ms=(time.monotonic() - start) * 1000,
                used_real_sandbox=False,
            )
