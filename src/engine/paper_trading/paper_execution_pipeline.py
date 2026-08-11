"""Layer 2 of the Paper Trading Account's two-layer execution engine (REL-034): intraday
tick-driven position management.

Genuinely wires up `src/engine/live/execution_pipeline.py`'s tick-handling mechanics for the
first time -- confirmed via grep that `LiveExecutionPipeline` has never been instantiated
anywhere in the running app. `PaperExecutionPipeline` mirrors its shape exactly (`Tick`,
`TradeSignal`, `SymbolState`, and the shared `run_risk_checks` free function are all reused
unmodified) but its final step calls `execute_paper_trade(...)` instead of
`broker.place_order(...)` -- building a full dummy `BrokerAdapter` implementation just to
satisfy an interface that doesn't fit the "instant fill against real depth" model already built
(src/engine/paper_trading/execution_service.py) would be needless indirection.

`kill_switch` is always the paper-account-scoped instance (src/engine/paper_trading/
paper_kill_switch.py) -- deliberately never the shared production singleton, see that module's
own docstring for why sharing it would be a real correctness bug in either direction.
"""

from dataclasses import dataclass, field

from src.brokers.base import BrokerAdapter
from src.engine.live.execution_pipeline import (
    PreTradeCheck,
    SignalGenerator,
    SymbolState,
    Tick,
    run_risk_checks,
)
from src.engine.paper_trading.execution_service import execute_paper_trade
from src.engine.risk.kill_switch import MaxDrawdownKillSwitch
from src.engine.risk.ws_latency_guard import WebSocketLatencyGuard
from src.models.paper_trading import PaperTrade


@dataclass
class PaperExecutionPipeline:
    broker: BrokerAdapter
    signal_generator: SignalGenerator
    kill_switch: MaxDrawdownKillSwitch
    account_id: str
    strategy_id: str | None = None
    latency_guard: WebSocketLatencyGuard | None = None
    pre_trade_checks: list[PreTradeCheck] = field(default_factory=list)
    _states: dict[str, SymbolState] = field(default_factory=dict, init=False)

    def state_for(self, symbol: str) -> SymbolState:
        if symbol not in self._states:
            self._states[symbol] = SymbolState(symbol=symbol)
        return self._states[symbol]

    async def handle_tick(self, tick: Tick) -> PaperTrade | None:
        """Same per-tick cycle as `LiveExecutionPipeline.handle_tick`: indicator update ->
        signal generation -> risk check -> execution -- routed to the real paper-trading fill
        simulator instead of a real broker order. Returns `None` when no signal fires (the
        common case, matching the live pipeline's own framing)."""
        state = self.state_for(tick.symbol)
        state.update(tick.price)

        signal = self.signal_generator(state)
        if signal is None:
            return None

        run_risk_checks(
            signal,
            kill_switch=self.kill_switch,
            latency_guard=self.latency_guard,
            pre_trade_checks=self.pre_trade_checks,
        )

        # signal.order_type/limit_price are ignored here -- execute_paper_trade always fills
        # against the real current quote (Phase_6 §5's "aggressive slippage... simulate
        # realistic market impact"), the same MARKET-only model every existing paper trade
        # already uses; a LIMIT signal isn't a real gap this pipeline introduces.
        return await execute_paper_trade(
            self.broker,
            symbol=signal.symbol,
            side=signal.side,
            quantity=signal.quantity,
            account_id=self.account_id,
            strategy_id=self.strategy_id,
        )
