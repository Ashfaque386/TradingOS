"""Broker factory tests (Phase 4 Epic E4.1): verifies the Zerodha-primary/Upstox-fallback
wiring from Phase_6_Trading_Engine_Design.md §6 is constructed correctly from settings, and
degrades gracefully when only one (or neither) broker is configured.

`_settings()` defaults `vault_addr=None` -- these are meant to be pure, hermetic unit tests of
the `.env`-fallback path (src/brokers/factory.py's `_zerodha_credentials`/`_upstox_credentials`
check Vault first); without disabling it, `Settings`'s own default `vault_addr` would make every
test here silently depend on whatever the real local dev Vault happens to have stored, which is
exactly the kind of hidden external dependency a unit test must not have. The Vault-preference
behavior itself is covered separately in tests/integration/test_vault.py, against the real dev
Vault on purpose.
"""

import pytest

from src.brokers.circuit_breaker import BrokerCircuitBreaker
from src.brokers.factory import NoBrokerConfigured, build_broker
from src.brokers.kite_connect_adapter import KiteConnectAdapter
from src.brokers.upstox_adapter import UpstoxAdapter
from src.core.config import Settings


def _settings(**overrides) -> Settings:
    overrides.setdefault("vault_addr", None)
    return Settings(**overrides)


def test_both_configured_wires_zerodha_primary_with_upstox_fallback():
    settings = _settings(
        zerodha_api_key="zk",
        zerodha_access_token="zt",
        upstox_access_token="ut",
        upstox_use_sandbox=True,
    )

    broker = build_broker(settings)

    assert isinstance(broker, BrokerCircuitBreaker)
    assert isinstance(broker.primary, KiteConnectAdapter)
    assert isinstance(broker.fallback, UpstoxAdapter)


def test_only_zerodha_configured_wires_a_circuit_breaker_with_no_fallback():
    settings = _settings(zerodha_api_key="zk", zerodha_access_token="zt", upstox_access_token=None)

    broker = build_broker(settings)

    assert isinstance(broker, BrokerCircuitBreaker)
    assert isinstance(broker.primary, KiteConnectAdapter)
    assert broker.fallback is None


def test_only_upstox_configured_returns_upstox_alone_not_wrapped():
    settings = _settings(zerodha_api_key=None, zerodha_access_token=None, upstox_access_token="ut")

    broker = build_broker(settings)

    assert isinstance(broker, UpstoxAdapter)
    assert not isinstance(broker, BrokerCircuitBreaker)


def test_neither_configured_raises():
    settings = _settings(zerodha_api_key=None, zerodha_access_token=None, upstox_access_token=None)

    with pytest.raises(NoBrokerConfigured):
        build_broker(settings)


def test_zerodha_configured_with_only_api_key_but_no_access_token_is_not_treated_as_configured():
    # Both fields are required for a usable adapter -- a bare api_key with no access_token
    # can't actually authenticate.
    settings = _settings(zerodha_api_key="zk", zerodha_access_token=None, upstox_access_token="ut")

    broker = build_broker(settings)

    assert isinstance(broker, UpstoxAdapter)
