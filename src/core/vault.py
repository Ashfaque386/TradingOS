"""Local dev Vault client (Phase 4 E4.1 exit criterion: "Wire Vault-issued short-lived tokens
for broker API key retrieval at execution time", Phase 3 §5 sequence diagram). Talks to the
real dev-mode Vault instance in docker-compose.yml's `vault` service via HashiCorp's official
`hvac` client -- a genuine KV v2 read/write round-trip against a real server, not a stub.

Scope, deliberately reduced from the full Phase_12_Security_Design.md §3 design:
  - Storage backend is Vault dev mode's in-memory store, not a real durable backend (Consul/
    Raft) -- restarting the `vault` container loses everything written to it, by design.
  - No auto-unseal, no TLS, a fixed root token baked into docker-compose.yml -- fine for a local
    container on a dev machine, never acceptable for production.
  - Only broker credentials (Zerodha/Upstox) are wired through Vault here. The JWT signing key
    (src/core/security.py) still comes from `Settings.jwt_secret_key`, NOT Vault's Transit
    engine (SEC-011) -- Transit-based signing-key issuance/rotation stays deferred, same as
    already documented in security.py's own module docstring.
  - No DB-004 BROKER_CREDENTIALS Postgres pointer table yet (Phase_11_Database_Design.md §2.2:
    a Postgres row holding a `vault_secret_path` pointer, never the secret itself). Credentials
    are read directly from Vault by a fixed KV path per broker (`secret/broker-credentials/
    <broker>`) instead -- a real follow-on, not required to prove the core capability this
    session set out to add: broker credentials genuinely retrieved from Vault at execution
    time, instead of only ever reading raw `.env` values.

Fails OPEN, not closed: if Vault is unreachable, or nothing has been written yet for a given
broker, callers get `None` back and fall through to `Settings` (the `.env`-sourced values
already used everywhere else in this codebase) -- see src/brokers/factory.py. This is the
deliberate opposite of Phase_12 SEC-020's fail-CLOSED production posture ("no trading without
valid secrets from Vault"); the point of a local dev Vault is that the system keeps working
whether or not Vault happens to have something for a given broker yet, not to block development
on a piece of optional local infrastructure.
"""

import logging
from typing import cast

import hvac

from src.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_KV_MOUNT = "secret"
_BROKER_CREDENTIALS_PREFIX = "broker-credentials"


def _client(settings: Settings) -> hvac.Client | None:
    if not settings.vault_addr or not settings.vault_token:
        return None
    client = hvac.Client(url=settings.vault_addr, token=settings.vault_token)
    try:
        if not client.is_authenticated():
            return None
    except Exception as exc:  # noqa: BLE001 -- Vault unreachable is a real, expected dev-mode state
        logger.info("Vault unreachable at %s: %s", settings.vault_addr, exc)
        return None
    return client


def write_broker_credentials(
    broker: str, credentials: dict[str, str], *, settings: Settings | None = None
) -> bool:
    """Returns True on a real successful write, False if Vault is unreachable or the write
    failed -- never raises for either case, so a missing/down dev Vault can't take anything
    else down with it.

    `settings` defaults to the real process-wide `get_settings()`, but callers that construct
    their own `Settings(...)` (e.g. unit tests exercising a specific credential combination)
    can pass it explicitly -- with `vault_addr=None`, this becomes a guaranteed no-op rather
    than silently reaching whatever Vault instance happens to be reachable at the default
    address, which would make an otherwise-hermetic unit test depend on live Vault state."""
    client = _client(settings or get_settings())
    if client is None:
        return False
    try:
        client.secrets.kv.v2.create_or_update_secret(
            mount_point=_KV_MOUNT,
            path=f"{_BROKER_CREDENTIALS_PREFIX}/{broker}",
            secret=credentials,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Vault write failed for broker=%s: %s", broker, exc)
        return False


def read_broker_credentials(
    broker: str, *, settings: Settings | None = None
) -> dict[str, str] | None:
    """Returns the stored credentials dict, or `None` if Vault is unreachable or nothing has
    been written yet for this broker -- callers (src/brokers/factory.py) fall back to `Settings`
    in either case, indistinguishably. See `write_broker_credentials` on the `settings` param."""
    client = _client(settings or get_settings())
    if client is None:
        return None
    try:
        response = client.secrets.kv.v2.read_secret_version(
            mount_point=_KV_MOUNT,
            path=f"{_BROKER_CREDENTIALS_PREFIX}/{broker}",
            raise_on_deleted_version=True,
        )
        return cast(dict[str, str], response["data"]["data"])
    except hvac.exceptions.InvalidPath:
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Vault read failed for broker=%s: %s", broker, exc)
        return None
