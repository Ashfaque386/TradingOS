"""Execution Agent (Phase 4 Epic E4.2), per Phase_4_AI_Agent_Design.md §10: bridges the Live
Strategy Engine and the Broker Adapter.

  "Translate abstract BUY/SELL signals into precise limit/market orders, manage partial fills,
  and handle API timeouts... Outputs: PostgreSQL Order State updates... Error Handling: If
  Broker API times out, implement exponential backoff. If filled partially, spawn a sub-task to
  track the remaining quantity."

Scope, per the agent's own prompt ("You do not make trading decisions or modify trading
strategies; your sole responsibility is to convert validated execution signals into
broker-specific orders"): this wraps whatever `BrokerAdapter` it's given (which may itself be a
`BrokerCircuitBreaker`, src/brokers/circuit_breaker.py) with (1) exponential-backoff retry on
transient *timeouts* specifically, (2) persistence of every order-state transition to Postgres
(DB-008 ORDERS, Phase_11_Database_Design.md), and (3) a spawned polling sub-task that keeps
tracking a partially-filled order until it reaches a terminal state.

Retry scope is deliberately narrow -- only `httpx.TimeoutException` triggers backoff here.
Sustained 5XX failures are the circuit breaker's job (failover to a different broker), not this
agent's; blindly retrying a 5xx here would double up with, and race, that mechanism.
"""

import asyncio
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.brokers.base import BrokerAdapter, OrderRequest, OrderResponse
from src.models.trading import Order as OrderModel
from src.observability.tracing import get_tracer

_tracer = get_tracer(__name__)

TERMINAL_STATUSES = frozenset({"FILLED", "CANCELLED", "REJECTED"})
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY_SECONDS = 0.5
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_MAX_POLLS = 60  # ~1 minute of polling at the default interval before giving up


@dataclass(frozen=True)
class ExecutionResult:
    order_response: OrderResponse
    latency_ms: float
    retry_count: int
    tracking_task: "asyncio.Task[None] | None" = None


class ExecutionFailed(Exception):
    """All retries exhausted without a successful order acknowledgement from the broker."""


class ExecutionAgent:
    def __init__(
        self,
        broker: BrokerAdapter,
        session_factory: Callable[[], AbstractContextManager[Session]],
        *,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        max_polls: int = DEFAULT_MAX_POLLS,
    ) -> None:
        self.broker = broker
        self.session_factory = session_factory
        self.max_retries = max_retries
        self.base_delay_seconds = base_delay_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.max_polls = max_polls

    async def execute_signal(
        self, order: OrderRequest, *, account_id: uuid.UUID, strategy_id: uuid.UUID
    ) -> ExecutionResult:
        """Places `order`, persists the resulting Order row, and -- if the order comes back
        partially filled -- spawns a background task tracking it to completion."""
        with _tracer.start_as_current_span("execution_agent.execute_signal") as span:
            span.set_attribute("symbol", order.symbol)
            span.set_attribute("side", order.side)

            start = time.perf_counter()
            response, retry_count = await self._place_with_backoff(order)
            latency_ms = (time.perf_counter() - start) * 1000
            span.set_attribute("retry_count", retry_count)
            span.set_attribute("broker_order_id", response.broker_order_id)

            with self.session_factory() as session:
                self._create_order_row(
                    session,
                    response,
                    account_id=account_id,
                    strategy_id=strategy_id,
                    latency_ms=latency_ms,
                )

            tracking_task = None
            if response.status not in TERMINAL_STATUSES:
                tracking_task = asyncio.create_task(
                    self._track_until_terminal(response.broker_order_id)
                )

            return ExecutionResult(
                order_response=response,
                latency_ms=latency_ms,
                retry_count=retry_count,
                tracking_task=tracking_task,
            )

    async def _place_with_backoff(self, order: OrderRequest) -> tuple[OrderResponse, int]:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return await self.broker.place_order(order), attempt
            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt == self.max_retries:
                    break
                await asyncio.sleep(self.base_delay_seconds * (2**attempt))
        raise ExecutionFailed(
            f"Order for {order.symbol} timed out after {self.max_retries + 1} attempts"
        ) from last_exc

    async def _track_until_terminal(self, broker_order_id: str) -> None:
        with _tracer.start_as_current_span("execution_agent.track_until_terminal") as span:
            span.set_attribute("broker_order_id", broker_order_id)
            for poll_count in range(self.max_polls):
                await asyncio.sleep(self.poll_interval_seconds)
                order_book = await self.broker.get_order_book()
                match = next((o for o in order_book if o.broker_order_id == broker_order_id), None)
                if match is None:
                    continue

                with self.session_factory() as session:
                    self._update_order_row(session, match)

                if match.status in TERMINAL_STATUSES:
                    span.set_attribute("final_status", match.status)
                    span.set_attribute("poll_count", poll_count + 1)
                    return
            # Gave up after max_polls without reaching a terminal state -- the Order row simply
            # stays non-terminal, which is itself the signal for a monitoring system to
            # investigate (per the agent's error-handling policy: "notify the appropriate
            # monitoring systems").
            span.set_attribute("final_status", "TIMED_OUT_POLLING")

    @staticmethod
    def _create_order_row(
        session: Session,
        response: OrderResponse,
        *,
        account_id: uuid.UUID,
        strategy_id: uuid.UUID,
        latency_ms: float,
    ) -> None:
        now = datetime.now(UTC)
        session.add(
            OrderModel(
                account_id=account_id,
                strategy_id=strategy_id,
                broker_order_id=response.broker_order_id,
                symbol=response.symbol,
                side=response.side,
                order_type=response.order_type,
                quantity=response.quantity,
                limit_price=response.limit_price,
                status=response.status,
                requested_at=now,
                acknowledged_at=None if response.status == "PENDING" else now,
                latency_ms=int(latency_ms),
                rejection_reason=response.rejection_reason,
            )
        )
        session.commit()

    @staticmethod
    def _update_order_row(session: Session, response: OrderResponse) -> None:
        row = session.scalar(
            select(OrderModel).where(OrderModel.broker_order_id == response.broker_order_id)
        )
        if row is None:
            return
        row.status = response.status
        row.rejection_reason = response.rejection_reason
        if row.acknowledged_at is None and response.status != "PENDING":
            row.acknowledged_at = datetime.now(UTC)
        session.commit()
