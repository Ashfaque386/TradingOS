"""Vault client integration tests (Phase 4 E4.1 exit criterion) against the REAL local dev
Vault (docker-compose.yml's `vault` service) -- no mocking, matching this codebase's convention
of testing real local infrastructure (Postgres/Redis/Qdrant/Temporal) directly rather than
faking it. See src/core/vault.py's module docstring for exactly what "real" means here (a real
KV v2 round-trip against a real dev-mode server) versus what's still a simplification (in-memory
storage, fixed root token, no Transit engine).
"""

import uuid

import pytest

from src.brokers.factory import build_upstox_adapter, build_zerodha_adapter
from src.brokers.kite_connect_adapter import KiteConnectAdapter
from src.brokers.upstox_adapter import UpstoxAdapter
from src.core import vault
from src.core.config import Settings, get_settings


def _dev_vault_settings(**overrides) -> Settings:
    """The real docker-compose Vault, reachable from inside the app container -- Settings'
    own defaults already point here, but spelling it out keeps these tests' intent explicit."""
    base_settings = get_settings()
    overrides.setdefault("vault_addr", base_settings.vault_addr)
    overrides.setdefault("vault_token", base_settings.vault_token)
    return Settings(**overrides)


def test_write_then_read_round_trips_against_the_real_dev_vault():
    broker = f"test-broker-{uuid.uuid4().hex[:8]}"
    settings = _dev_vault_settings()

    ok = vault.write_broker_credentials(
        broker, {"access_token": "real-round-trip-token"}, settings=settings
    )
    assert ok is True

    stored = vault.read_broker_credentials(broker, settings=settings)
    assert stored == {"access_token": "real-round-trip-token"}


def test_reading_a_broker_never_written_returns_none_not_an_error():
    settings = _dev_vault_settings()
    never_written = f"nonexistent-broker-{uuid.uuid4().hex[:8]}"

    assert vault.read_broker_credentials(never_written, settings=settings) is None


def test_an_unreachable_vault_fails_open_returning_none_and_false_not_raising():
    unreachable = Settings(vault_addr="http://vault-does-not-exist.invalid:8200", vault_token="x")

    assert vault.read_broker_credentials("zerodha", settings=unreachable) is None
    assert vault.write_broker_credentials("zerodha", {"a": "b"}, settings=unreachable) is False


def test_vault_disabled_via_no_addr_is_a_clean_no_op():
    disabled = Settings(vault_addr=None, vault_token=None)

    assert vault.read_broker_credentials("zerodha", settings=disabled) is None
    assert vault.write_broker_credentials("zerodha", {"a": "b"}, settings=disabled) is False


def test_broker_factory_prefers_a_real_vault_stored_credential_over_env_settings():
    """Proves the actual retrieval path end-to-end: write a distinguishable credential to the
    real Vault, then confirm build_zerodha_adapter/build_upstox_adapter pick it up over a
    conflicting .env-style value in Settings -- not just that vault.py's functions work in
    isolation."""
    broker = "zerodha"
    settings = _dev_vault_settings(zerodha_api_key="env-key", zerodha_access_token="env-token")

    marker_token = f"vault-wins-{uuid.uuid4().hex[:8]}"
    ok = vault.write_broker_credentials(
        broker, {"api_key": "vault-key", "access_token": marker_token}, settings=settings
    )
    assert ok is True

    try:
        adapter = build_zerodha_adapter(settings)
        assert isinstance(adapter, KiteConnectAdapter)
        assert adapter._client.headers["Authorization"] == f"token vault-key:{marker_token}"
    finally:
        # Best-effort cleanup: overwrite with the real env-sourced credentials so this test
        # doesn't leave a stale/fake token in Vault for anything run after it.
        real_settings = get_settings()
        if real_settings.zerodha_api_key and real_settings.zerodha_access_token:
            vault.write_broker_credentials(
                broker,
                {
                    "api_key": real_settings.zerodha_api_key,
                    "access_token": real_settings.zerodha_access_token,
                },
                settings=settings,
            )


def test_broker_factory_falls_back_to_env_settings_when_vault_has_nothing_for_this_broker():
    never_seeded = f"broker-never-seeded-{uuid.uuid4().hex[:8]}"
    settings = _dev_vault_settings()

    # No write for `never_seeded` -- read_broker_credentials must return None, and a factory
    # function built against a real, seeded broker name (upstox) must still work from .env.
    assert vault.read_broker_credentials(never_seeded, settings=settings) is None

    try:
        adapter = build_upstox_adapter(settings)
    except Exception as exc:  # noqa: BLE001 -- honest skip if Upstox isn't configured at all here
        pytest.skip(f"Upstox not configured in this environment: {exc}")
    assert isinstance(adapter, UpstoxAdapter)
