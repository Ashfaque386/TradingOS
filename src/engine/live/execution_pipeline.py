"""Live execution pipeline (Phase 4 Epic E4.2), per Phase_6_Trading_Engine_Design.md §5 "Live
Execution Engine (Polars-Driven)":

  "1. Data Ingestion: Redis Pub/Sub pushes tick data to the live strategy process.
   2. Signal Generation: Polars processes the tick, updating technical indicators in
      microseconds.
   3. Risk Check: Signal is evaluated against the Portfolio Engine.
   4. Broker Routing: Signal sent to the Broker Layer.
   Latency: The entire cycle from receiving the WebSocket tick to firing the HTTP POST order
   request to the broker must complete in under 50 milliseconds." (NFR-02)

Strategy-specific signal generation is intentionally NOT hardcoded here -- an AI-generated
strategy's logic (Phase 4 AI Agent Design) is supplied as a `SignalGenerator` callable, same
"caller supplies the strategy" pattern already used by src/engine/optimization/walk_forward.py
and optuna_sweep.py. This module owns the pipeline mechanics: rolling per-symbol tick state,
the hardcoded risk gate, and broker routing -- not any particular trading rule.

The Max Drawdown Kill Switch (src/engine/risk/kill_switch.py) is checked on every single signal
before it reaches the broker, per Phase_6 §4 ("the AI cannot modify these rules... final
gatekeeper"). The WebSocket Latency Guard (src/engine/risk/ws_latency_guard.py) is checked too,
per Phase_9_Master_Implementation_Guide.md §5 Risk Register ("Prometheus alerts if WebSocket
latency > 100ms... pauses live trading until synced") -- unlike the kill switch, it clears
itself automatically once latency recovers. Correlation/naked-options checks are portfolio-level,
pre-deployment gates (evaluated once per strategy, not per tick) and are NOT re-run here;
`pre_trade_checks` exists as an extension point for additional hardcoded per-signal gates
without changing this class.
"""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from src.brokers.base import BrokerAdapter, OrderRequest, OrderResponse, OrderType, Side
from src.engine.risk.kill_switch import MaxDrawdownKillSwitch
from src.engine.risk.ws_latency_guard import WebSocketLatencyGuard
from src.observability.tracing import get_tracer

_tracer = get_tracer(__name__)


@dataclass(frozen=True)
class Tick:
    symbol: str
    price: float
    timestamp: datetime


@dataclass(frozen=True)
class TradeSignal:
    symbol: str
    side: Side
    quantity: int
    order_type: OrderType = "MARKET"
    limit_price: float | None = None


class RiskRejected(Exception):
    """Raised when a signal fails a hardcoded risk check and must not reach the broker."""


@dataclass
class SymbolState:
    """Rolling per-symbol tick buffer, O(1) update per tick (a bounded deque, not an
    ever-growing list) -- this is the "Polars processes the tick... in microseconds" step in
    spirit; a fixed-size ring buffer is the cheapest possible per-tick indicator update, well
    within the <50ms end-to-end budget."""

    symbol: str
    max_history: int = 200
    prices: deque[float] = field(default_factory=deque, init=False)

    def __post_init__(self) -> None:
        self.prices = deque(maxlen=self.max_history)

    def update(self, price: float) -> None:
        self.prices.append(price)

    def sma(self, window: int) -> float | None:
        if len(self.prices) < window:
            return None
        recent = list(self.prices)[-window:]
        return sum(recent) / window


SignalGenerator = Callable[[SymbolState], TradeSignal | None]
PreTradeCheck = Callable[[TradeSignal], None]  # raises RiskRejected to veto


@dataclass
class LiveExecutionPipeline:
    broker: BrokerAdapter
    signal_generator: SignalGenerator
    kill_switch: MaxDrawdownKillSwitch
    latency_guard: WebSocketLatencyGuard | None = None
    pre_trade_checks: list[PreTradeCheck] = field(default_factory=list)
    _states: dict[str, SymbolState] = field(default_factory=dict, init=False)

    def state_for(self, symbol: str) -> SymbolState:
        if symbol not in self._states:
            self._states[symbol] = SymbolState(symbol=symbol)
        return self._states[symbol]

    async def handle_tick(self, tick: Tick) -> OrderResponse | None:
        """The full per-tick cycle: indicator update -> signal generation -> risk check ->
        broker routing. Returns `None` when no signal fires (the common case -- most ticks
        don't trigger a trade).

        Wrapped in a span (Phase_8_DevOps_Architecture.md §5 distributed tracing): the broker
        call below goes through `httpx.AsyncClient`, which OpenTelemetry's httpx
        instrumentation auto-instruments as a child span under this one -- so a single trace ID
        covers "Execution Engine" through "Broker API" with no extra wiring needed there."""
        with _tracer.start_as_current_span("execution_engine.handle_tick") as span:
            span.set_attribute("symbol", tick.symbol)

            state = self.state_for(tick.symbol)
            state.update(tick.price)

            signal = self.signal_generator(state)
            if signal is None:
                return None

            self._run_risk_checks(signal)

            order = OrderRequest(
                symbol=signal.symbol,
                side=signal.side,
                order_type=signal.order_type,
                quantity=signal.quantity,
                limit_price=signal.limit_price,
            )
            return await self.broker.place_order(order)

    def _run_risk_checks(self, signal: TradeSignal) -> None:
        if self.kill_switch.triggered:
            raise RiskRejected(f"Kill switch is triggered -- rejecting signal for {signal.symbol}")
        if self.latency_guard is not None and self.latency_guard.paused:
            raise RiskRejected(
                f"WebSocket latency guard is paused ({self.latency_guard.last_latency_seconds}s "
                f"> {self.latency_guard.threshold_seconds}s threshold) -- rejecting signal for "
                f"{signal.symbol} until the feed is synced"
            )
        for check in self.pre_trade_checks:
            check(signal)
