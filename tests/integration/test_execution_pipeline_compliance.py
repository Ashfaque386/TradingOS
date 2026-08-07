"""Compliance pre-trade check (AGT-020, REL-006 E6.1) wired into the real LiveExecutionPipeline
against real Postgres -- exit criterion 3: "Compliance Agent blocks a real synthetic
naked-options order request end-to-end, with ComplianceVerdict and rejection reason persisted."

`compliance_pre_trade_check` writes its AuditLog row via its own internal, real,
committed session (matching production: a Block means no Order row will ever exist, so this is
the only persisted record) -- that row is never deleted afterward. Deleting a committed AuditLog
row, even an untampered one, orphans any real row written after it and permanently breaks
verify_chain() for later test runs (see test_audit_tamper_detection.py's module docstring). The
assertion below reads the MOST RECENT matching row rather than asserting an exact count, so
harmless accumulation across repeated test runs doesn't make this test flaky.
"""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from src.brokers.base import BrokerAdapter, Margin, OrderRequest, OrderResponse, Position, Quote
from src.core.db import get_session
from src.engine.live.execution_pipeline import (
    LiveExecutionPipeline,
    RiskRejected,
    Tick,
    TradeSignal,
    compliance_pre_trade_check,
)
from src.engine.risk.kill_switch import MaxDrawdownKillSwitch
from src.engine.risk.naked_options_scanner import OptionLeg
from src.models.audit import AuditLog


class _AssertNeverCalledBroker(BrokerAdapter):
    """Enforces "never place a real order" at the test level, not just via an exception check:
    if a Block somehow failed to stop the signal, this broker itself fails the test loudly."""

    async def place_order(self, order: OrderRequest) -> OrderResponse:
        raise AssertionError("place_order must never be called for a compliance-blocked signal")

    async def modify_order(self, broker_order_id, **kwargs) -> OrderResponse:
        raise AssertionError("not used in this test")

    async def cancel_order(self, broker_order_id: str) -> OrderResponse:
        raise AssertionError("not used in this test")

    async def get_order_book(self) -> list[OrderResponse]:
        return []

    async def get_margin(self) -> Margin:
        raise AssertionError("not used in this test")

    async def get_positions(self) -> list[Position]:
        return []

    async def get_quote(self, symbol: str) -> Quote:
        raise AssertionError("not used in this test")

    async def get_option_chain(self, underlying: str, expiry):
        raise AssertionError("not used in this test")

    async def list_expiries(self, underlying: str):
        raise AssertionError("not used in this test")


def test_naked_option_signal_is_blocked_end_to_end_and_never_reaches_the_broker():
    naked_short_call = OptionLeg(
        symbol="RELIANCE", option_type="CE", strike=2600, side="sell", quantity=50
    )
    signal = TradeSignal(
        symbol="RELIANCE", side="SELL", quantity=50, option_legs=[naked_short_call]
    )

    def signal_generator(state):
        return signal

    pipeline = LiveExecutionPipeline(
        broker=_AssertNeverCalledBroker(),
        signal_generator=signal_generator,
        kill_switch=MaxDrawdownKillSwitch(),
        pre_trade_checks=[compliance_pre_trade_check],
    )

    with pytest.raises(RiskRejected, match="Compliance block"):
        asyncio.run(
            pipeline.handle_tick(Tick(symbol="RELIANCE", price=2550.0, timestamp=datetime.now(UTC)))
        )

    with get_session() as session:
        latest = session.scalars(
            select(AuditLog)
            .where(AuditLog.action == "ORDER_BLOCKED_COMPLIANCE")
            .order_by(AuditLog.id.desc())
            .limit(1)
        ).first()
        assert latest is not None
        assert latest.after_state["symbol"] == "RELIANCE"
        assert any(v["rule"] == "BR-02_NAKED_OPTIONS" for v in latest.after_state["violations"])


def test_a_properly_hedged_signal_passes_compliance_and_reaches_the_broker():
    sold_call = OptionLeg(
        symbol="RELIANCE", option_type="CE", strike=2600, side="sell", quantity=50
    )
    hedge_call = OptionLeg(
        symbol="RELIANCE", option_type="CE", strike=2700, side="buy", quantity=50
    )
    signal = TradeSignal(
        symbol="RELIANCE", side="SELL", quantity=50, option_legs=[sold_call, hedge_call]
    )

    class _RecordingBroker(_AssertNeverCalledBroker):
        called = False

        async def place_order(self, order: OrderRequest) -> OrderResponse:
            _RecordingBroker.called = True
            return OrderResponse(
                broker_order_id="test-order-1",
                status="PENDING",
                symbol=order.symbol,
                side=order.side,
                order_type=order.order_type,
                quantity=order.quantity,
            )

    pipeline = LiveExecutionPipeline(
        broker=_RecordingBroker(),
        signal_generator=lambda state: signal,
        kill_switch=MaxDrawdownKillSwitch(),
        pre_trade_checks=[compliance_pre_trade_check],
    )

    result = asyncio.run(
        pipeline.handle_tick(Tick(symbol="RELIANCE", price=2550.0, timestamp=datetime.now(UTC)))
    )
    assert result is not None
    assert _RecordingBroker.called is True
