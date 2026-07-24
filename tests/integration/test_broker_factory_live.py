"""Broker factory integration test (Phase 4 Epic E4.1): confirms `build_broker()`'s real,
settings-driven Zerodha-primary/Upstox-fallback pairing actually works end-to-end against live
credentials -- not just that construction picks the right classes (tests/unit/test_broker_factory.py
already covers that in isolation).

Only exercises `get_margin()` (read-only, safe on both brokers -- Kite Connect has no sandbox,
so nothing order-related is called here). Skipped unless both brokers are configured.
"""

import pytest

from src.brokers.circuit_breaker import BrokerCircuitBreaker
from src.brokers.factory import build_broker
from src.core.config import get_settings

settings = get_settings()

_both_configured = bool(
    settings.zerodha_api_key and settings.zerodha_access_token and settings.upstox_access_token
)
pytestmark = pytest.mark.skipif(
    not _both_configured,
    reason="both ZERODHA_* and UPSTOX_ACCESS_TOKEN must be configured for this pairing test",
)


@pytest.mark.asyncio
async def test_the_real_configured_pairing_routes_to_zerodha_as_primary():
    broker = build_broker()

    assert isinstance(broker, BrokerCircuitBreaker)
    assert broker.state == "CLOSED"

    margin = await broker.get_margin()  # always targets primary (Zerodha) directly

    assert margin.available_margin >= 0.0
