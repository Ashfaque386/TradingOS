"""Broker factory (Phase 4 Epic E4.1): wires the real Zerodha/Upstox pairing named in
Phase_6_Trading_Engine_Design.md §6:

  "Zerodha Implementation (KiteConnectAdapter): Primary executor... Upstox Implementation
  (UpstoxAdapter): Secondary executor/fallback."

Built from settings rather than hardcoding which adapter is "primary" in code -- so the pairing
degrades gracefully in dev: if only one broker is configured (the common case while building
this system), that one runs alone (with no automated failover, since there's nothing to fail
over to) instead of the whole system failing to start.
"""

from src.brokers.base import BrokerAdapter
from src.brokers.circuit_breaker import BrokerCircuitBreaker
from src.brokers.kite_connect_adapter import KiteConnectAdapter
from src.brokers.upstox_adapter import UpstoxAdapter
from src.core import vault
from src.core.config import Settings, get_settings


class NoBrokerConfigured(Exception):
    """Raised when neither Zerodha nor Upstox credentials are configured -- there is no broker
    to route orders to at all."""


def _zerodha_credentials(settings: Settings) -> tuple[str, str] | None:
    """(api_key, access_token), preferring Vault (src/core/vault.py) over raw `.env`-sourced
    Settings -- Vault is the intended execution-time source (Phase 3 §5 sequence diagram);
    `.env` is the fallback when Vault has nothing stored yet or is unreachable, not vice versa."""
    stored = vault.read_broker_credentials("zerodha", settings=settings)
    if stored and stored.get("api_key") and stored.get("access_token"):
        return stored["api_key"], stored["access_token"]
    if settings.zerodha_api_key and settings.zerodha_access_token:
        return settings.zerodha_api_key, settings.zerodha_access_token
    return None


def _upstox_credentials(settings: Settings) -> tuple[str, bool] | None:
    """(access_token, use_sandbox), same Vault-first precedence as `_zerodha_credentials`."""
    stored = vault.read_broker_credentials("upstox", settings=settings)
    if stored and stored.get("access_token"):
        use_sandbox = stored.get("use_sandbox", str(settings.upstox_use_sandbox)).lower() != "false"
        return stored["access_token"], use_sandbox
    if settings.upstox_access_token:
        return settings.upstox_access_token, settings.upstox_use_sandbox
    return None


def build_broker(settings: Settings | None = None) -> BrokerAdapter:
    """Returns the live-execution entry point per Phase_6 §6's Zerodha-primary/Upstox-fallback
    design: a `BrokerCircuitBreaker` wrapping `KiteConnectAdapter` as primary and
    `UpstoxAdapter` as fallback, when both are configured. Falls back to whichever single
    adapter is configured if only one is; raises `NoBrokerConfigured` if neither is."""
    settings = settings or get_settings()

    zerodha_creds = _zerodha_credentials(settings)
    zerodha: KiteConnectAdapter | None = None
    if zerodha_creds is not None:
        zerodha = KiteConnectAdapter(api_key=zerodha_creds[0], access_token=zerodha_creds[1])

    upstox_creds = _upstox_credentials(settings)
    upstox: UpstoxAdapter | None = None
    if upstox_creds is not None:
        upstox = UpstoxAdapter(access_token=upstox_creds[0], use_sandbox=upstox_creds[1])

    if zerodha is not None:
        return BrokerCircuitBreaker(primary=zerodha, fallback=upstox)
    if upstox is not None:
        return upstox

    raise NoBrokerConfigured(
        "Neither ZERODHA_ACCESS_TOKEN nor UPSTOX_ACCESS_TOKEN is configured (checked Vault, "
        "then .env) -- there is no broker to route orders to. See .env.example for how to "
        "configure either, or scripts/seed_vault_broker_credentials.py to push them into Vault."
    )


def build_zerodha_adapter(settings: Settings | None = None) -> KiteConnectAdapter:
    """A single named adapter, not the primary/fallback pairing -- used where the caller
    specifically needs *this* broker (e.g. Shadow Mode, src/brokers/shadow_mode.py, which
    behaves differently per broker and needs to know which concrete adapter it holds)."""
    settings = settings or get_settings()
    creds = _zerodha_credentials(settings)
    if creds is None:
        raise NoBrokerConfigured(
            "Zerodha is not configured (checked Vault, then ZERODHA_API_KEY/ACCESS_TOKEN)"
        )
    return KiteConnectAdapter(api_key=creds[0], access_token=creds[1])


def build_upstox_adapter(settings: Settings | None = None) -> UpstoxAdapter:
    settings = settings or get_settings()
    creds = _upstox_credentials(settings)
    if creds is None:
        raise NoBrokerConfigured(
            "Upstox is not configured (checked Vault, then UPSTOX_ACCESS_TOKEN)"
        )
    return UpstoxAdapter(access_token=creds[0], use_sandbox=creds[1])
