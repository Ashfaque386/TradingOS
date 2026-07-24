"""NFR-02 real-broker latency test (Phase 4 Epic E4.2 exit criterion), closing a real gap found
during this session's Phase 4 audit: `tests/unit/test_execution_pipeline.py`'s
`test_nfr02_per_tick_latency_stays_under_50ms_at_p95` only ever exercised a `FakeBrokerAdapter`
(an in-memory stub, no network) -- it proved the pipeline's own logic is fast, not that the
system genuinely meets NFR-02 against a real broker. This test runs the real
`LiveExecutionPipeline` against Upstox's real sandbox (Upstox has a genuine, documented
risk-free sandbox; Zerodha does not, so it is never used here -- see
src/brokers/kite_connect_adapter.py's module docstring). Skipped entirely if Upstox isn't
configured, and honestly skips (not fails) if a real sandbox call errors out (e.g. today's daily
access-token expiry), matching every other real-broker test in this codebase.

What NFR-02 actually says (`Phase_2_Software_Requirements_Specification.md` §5): "Live order
execution latency (from signal generation to broker API call) must be under 50 milliseconds" --
scoped to TradingOS's own dispatch overhead (tick receipt -> indicator update -> risk checks ->
handing the order off to the broker adapter), not to the broker's network round-trip time, which
depends on Upstox's sandbox and the network path to it, neither controlled by this codebase. The
pipeline module's own docstring (src/engine/live/execution_pipeline.py) says the same thing:
"the entire cycle from receiving the WebSocket tick to firing the HTTP POST order request." So
this test asserts the dispatch-to-firing time against the <50ms budget, and separately reports
(without asserting) the real end-to-end round-trip time including Upstox's actual response, so
the full real number is visible rather than hidden.
"""

import asyncio
import time
from datetime import UTC, datetime

import pytest

from src.brokers.base import (
    BrokerAdapter,
    Margin,
    OrderRequest,
    OrderResponse,
    OrderType,
    Position,
    Quote,
)
from src.brokers.upstox_adapter import UpstoxAdapter
from src.core.config import get_settings
from src.engine.live.execution_pipeline import LiveExecutionPipeline, SymbolState, Tick, TradeSignal
from src.engine.risk.kill_switch import MaxDrawdownKillSwitch

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not settings.upstox_access_token,
    reason="UPSTOX_ACCESS_TOKEN not configured -- see .env.example for the sandbox token flow",
)

N_REAL_ORDERS = 8  # a real network call per iteration
# Upstox's sandbox rate-limits aggressively -- confirmed empirically (a first attempt at N=20
# with no pacing got a real 429 from the sandbox partway through). Pacing is applied *between*
# iterations, outside the timed dispatch window, so it doesn't distort the latency measurement.
PACING_SECONDS_BETWEEN_ORDERS = 1.0


class _TimingBrokerWrapper(BrokerAdapter):
    """Wraps a real adapter, splitting each `place_order` call into the two latencies this test
    cares about separately: `entry_times` (when the pipeline handed off to the broker -- the
    NFR-02-relevant instant) and `round_trip_seconds` (how long the real network call took after
    that, informational only). Delegates every other method unchanged."""

    def __init__(self, real: BrokerAdapter) -> None:
        self._real = real
        self.entry_times: list[float] = []
        self.round_trip_seconds: list[float] = []

    async def place_order(self, order: OrderRequest) -> OrderResponse:
        entry = time.perf_counter()
        self.entry_times.append(entry)
        result = await self._real.place_order(order)
        self.round_trip_seconds.append(time.perf_counter() - entry)
        return result

    async def modify_order(
        self,
        broker_order_id: str,
        *,
        quantity: int | None = None,
        order_type: OrderType | None = None,
        limit_price: float | None = None,
        trigger_price: float | None = None,
    ) -> OrderResponse:
        return await self._real.modify_order(
            broker_order_id,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            trigger_price=trigger_price,
        )

    async def cancel_order(self, broker_order_id: str) -> OrderResponse:
        return await self._real.cancel_order(broker_order_id)

    async def get_order_book(self) -> list[OrderResponse]:
        return await self._real.get_order_book()

    async def get_margin(self) -> Margin:
        return await self._real.get_margin()

    async def get_positions(self) -> list[Position]:
        return await self._real.get_positions()

    async def get_quote(self, symbol: str) -> Quote:
        return await self._real.get_quote(symbol)


def _percentile(sorted_values: list[float], pct: float) -> float:
    return sorted_values[int(len(sorted_values) * pct)]


@pytest.mark.asyncio
async def test_nfr02_dispatch_latency_against_a_real_upstox_sandbox_order():
    async with UpstoxAdapter(
        access_token=settings.upstox_access_token, use_sandbox=settings.upstox_use_sandbox
    ) as real_adapter:
        try:
            instrument_key = await real_adapter.search_instrument_key("RELIANCE")
        except Exception as exc:  # noqa: BLE001 -- honest skip, not a fabricated pass
            pytest.skip(f"Real Upstox sandbox call failed (likely today's expired token): {exc}")

        wrapper = _TimingBrokerWrapper(real_adapter)

        def always_buy_far_below_market(state: SymbolState) -> TradeSignal | None:
            # LIMIT far below market so the order stays open rather than filling immediately --
            # same technique test_upstox_sandbox.py uses, keeps cancellation deterministic.
            return TradeSignal(
                symbol=state.symbol, side="BUY", quantity=1, order_type="LIMIT", limit_price=1.0
            )

        pipeline = LiveExecutionPipeline(
            broker=wrapper,
            signal_generator=always_buy_far_below_market,
            kill_switch=MaxDrawdownKillSwitch(),
        )

        tick_starts: list[float] = []
        placed_order_ids: list[str] = []
        try:
            for i in range(N_REAL_ORDERS):
                tick_starts.append(time.perf_counter())
                try:
                    result = await pipeline.handle_tick(
                        Tick(symbol=instrument_key, price=2500.0 + i, timestamp=datetime.now(UTC))
                    )
                except Exception as exc:  # noqa: BLE001 -- honest skip, not a fabricated pass
                    pytest.skip(f"Real Upstox sandbox order placement failed mid-run: {exc}")
                assert result is not None
                placed_order_ids.append(result.broker_order_id)
                if i < N_REAL_ORDERS - 1:
                    await asyncio.sleep(PACING_SECONDS_BETWEEN_ORDERS)
        finally:
            for order_id in placed_order_ids:
                try:
                    await real_adapter.cancel_order(order_id)
                except Exception:  # noqa: BLE001 -- best-effort sandbox cleanup, not the assertion under test
                    pass
                await asyncio.sleep(PACING_SECONDS_BETWEEN_ORDERS)

    assert len(wrapper.entry_times) == len(tick_starts)
    dispatch_durations = sorted(
        entry - start for entry, start in zip(wrapper.entry_times, tick_starts, strict=True)
    )
    p95_dispatch = _percentile(dispatch_durations, 0.95)

    round_trips = sorted(wrapper.round_trip_seconds)
    p95_round_trip = _percentile(round_trips, 0.95)
    print(
        f"\nReal Upstox sandbox: dispatch p95={p95_dispatch * 1000:.2f}ms (NFR-02 budget), "
        f"real network round-trip p95={p95_round_trip * 1000:.2f}ms (informational -- broker/"
        f"network-dependent, not asserted)"
    )

    assert p95_dispatch < 0.05, (
        f"NFR-02 violated: p95 dispatch latency (tick receipt -> handoff to the real broker "
        f"adapter) was {p95_dispatch * 1000:.2f}ms against a real Upstox sandbox order (limit 50ms)"
    )
