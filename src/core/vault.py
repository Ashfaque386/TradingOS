"""Local Vault client (Phase 4 E4.1 exit criterion: "Wire Vault-issued short-lived tokens
for broker API key retrieval at execution time", Phase 3 §5 sequence diagram). Talks to the
real Vault instance in docker-compose.yml's `vault` service via HashiCorp's official
`hvac` client -- a genuine KV v2 read/write round-trip against a real server, not a stub.

REL-015 E15.1 (GLH-01): the `vault` service moved from `-dev` mode to a real server (persistent
`file` storage backend, genuine seal/unseal lifecycle, a real random root token distributed via
`scripts/vault_auto_unseal.py` + `scripts/docker-entrypoint-with-vault-token.sh`, TLS still
disabled -- see docker/vault/config.hcl's own comment on why that's fine on this single-host
internal network). `ensure_kv_engine()` below self-heals the KV v2 mount real server mode doesn't
auto-provide (dev mode did), the same way `vault_transit.ensure_transit_key()` already self-heals
the Transit engine.

Scope, deliberately reduced from the full Phase_12_Security_Design.md §3 design:
  - No TLS on this internal-only Docker bridge listener -- same posture as every other internal
    service (Postgres/Redis/Qdrant) on this single-host topology (Phase 1 ADR 10).
  - Broker credentials (Zerodha/Upstox) and LLM provider API keys (OpenAI/Anthropic/DeepSeek/
    Gemini/HuggingFace/OpenCode Zen -- REL-002 E2.2) are both wired through Vault here, via the
    same generic KV v2 read/write helpers (`_read_secret`/`_write_secret`). JWT signing
    (src/core/security.py) uses Vault's Transit engine, not this module's KV-v2 helpers --
    see src/core/vault_transit.py (REL-007 E7.2), which is deliberately fail-CLOSED rather than
    fail-open like everything else in this file.
  - No DB-004 BROKER_CREDENTIALS Postgres pointer table yet (Phase_11_Database_Design.md §2.2:
    a Postgres row holding a `vault_secret_path` pointer, never the secret itself). Secrets are
    read directly from Vault by a fixed KV path per broker/provider (`secret/broker-credentials/
    <broker>`, `secret/llm-provider-keys/<provider>`) instead -- a real follow-on, not required
    to prove the core capability this session set out to add: credentials genuinely retrieved
    from Vault at execution time, instead of only ever reading raw `.env` values.

Fails OPEN, not closed: if Vault is unreachable, or nothing has been written yet for a given
broker, callers get `None` back and fall through to `Settings` (the `.env`-sourced values
already used everywhere else in this codebase) -- see src/brokers/factory.py. This is the
deliberate opposite of Phase_12 SEC-020's fail-CLOSED production posture ("no trading without
valid secrets from Vault"); the point of a local dev Vault is that the system keeps working
whether or not Vault happens to have something for a given broker yet, not to block development
on a piece of optional local infrastructure.
"""

import logging
from dataclasses import dataclass
from typing import cast

import hvac

from src.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_KV_MOUNT = "secret"
_BROKER_CREDENTIALS_PREFIX = "broker-credentials"
_LLM_PROVIDER_KEYS_PREFIX = "llm-provider-keys"
_MFA_SECRETS_PREFIX = "mfa-secrets"
_WEBHOOK_SECRETS_PREFIX = "webhook-secrets"
_BOT_TOKENS_PREFIX = "bot-tokens"


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


def ensure_kv_engine(settings: Settings | None = None) -> None:
    """REL-015 E15.1 (GLH-01): idempotent setup, mirroring `vault_transit.ensure_transit_key()`.

    `-dev` mode auto-mounts a KV v2 engine at `secret/`; the real server mode this project moved
    to (docker/vault/config.hcl) mounts nothing by default, so every `_read_secret`/`_write_secret`
    call above 404'd ("no handler for route") the first time this ran against the new real Vault,
    until this was added. Safe to call on every app boot, same as its Transit sibling -- does
    nothing once the mount already exists."""
    settings = settings or get_settings()
    client = _client(settings)
    if client is None:
        return
    try:
        client.sys.enable_secrets_engine(
            backend_type="kv", path=_KV_MOUNT, options={"version": "2"}
        )
        logger.info("Enabled the KV v2 secrets engine at '%s/' (real Vault mode).", _KV_MOUNT)
    except hvac.exceptions.InvalidRequest as exc:
        if "path is already in use" not in str(exc):
            raise


def _write_secret(path: str, secret: dict[str, str], *, settings: Settings) -> bool:
    """Returns True on a real successful write, False if Vault is unreachable or the write
    failed -- never raises for either case, so a missing/down dev Vault can't take anything
    else down with it."""
    client = _client(settings)
    if client is None:
        return False
    try:
        client.secrets.kv.v2.create_or_update_secret(
            mount_point=_KV_MOUNT, path=path, secret=secret
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Vault write failed for path=%s: %s", path, exc)
        return False


def _read_secret(path: str, *, settings: Settings) -> dict[str, str] | None:
    """Returns the stored secret dict, or `None` if Vault is unreachable or nothing has been
    written yet at this path -- callers fall back to `Settings` in either case,
    indistinguishably."""
    client = _client(settings)
    if client is None:
        return None
    try:
        response = client.secrets.kv.v2.read_secret_version(
            mount_point=_KV_MOUNT, path=path, raise_on_deleted_version=True
        )
        return cast(dict[str, str], response["data"]["data"])
    except hvac.exceptions.InvalidPath:
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Vault read failed for path=%s: %s", path, exc)
        return None


@dataclass(frozen=True)
class VaultStatus:
    reachable: bool
    kv_engine_mounted: bool | None
    vault_addr: str | None


def vault_status(*, settings: Settings | None = None) -> VaultStatus:
    """REL-062 (API-079). A real, non-secret reachability check -- `_client()` already does a
    genuine `client.is_authenticated()` round-trip against the live Vault instance on every
    secret read/write; this exposes that same check on its own, without needing to read or
    write an actual secret path to prove it. `kv_engine_mounted` distinguishes "Vault is up but
    `ensure_kv_engine()` hasn't run yet" from "Vault itself is down" -- both real, different
    failure modes, per real Vault server-mode migration REL-015 documented."""
    settings = settings or get_settings()
    client = _client(settings)
    if client is None:
        return VaultStatus(reachable=False, kv_engine_mounted=None, vault_addr=settings.vault_addr)
    try:
        mounts = client.sys.list_mounted_secrets_engines()
        kv_mounted = f"{_KV_MOUNT}/" in mounts.get("data", mounts)
    except Exception as exc:  # noqa: BLE001 -- a real, expected transient Vault API hiccup
        logger.info("Vault mount-list check failed at %s: %s", settings.vault_addr, exc)
        kv_mounted = None
    return VaultStatus(reachable=True, kv_engine_mounted=kv_mounted, vault_addr=settings.vault_addr)


def _delete_secret(path: str, *, settings: Settings) -> bool:
    """Returns True on a real successful delete (or if nothing was there to delete -- Vault
    treats deleting a nonexistent path as a no-op success), False if Vault is unreachable."""
    client = _client(settings)
    if client is None:
        return False
    try:
        client.secrets.kv.v2.delete_metadata_and_all_versions(mount_point=_KV_MOUNT, path=path)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Vault delete failed for path=%s: %s", path, exc)
        return False


def write_broker_credentials(
    broker: str, credentials: dict[str, str], *, settings: Settings | None = None
) -> bool:
    """`settings` defaults to the real process-wide `get_settings()`, but callers that construct
    their own `Settings(...)` (e.g. unit tests exercising a specific credential combination)
    can pass it explicitly -- with `vault_addr=None`, this becomes a guaranteed no-op rather
    than silently reaching whatever Vault instance happens to be reachable at the default
    address, which would make an otherwise-hermetic unit test depend on live Vault state."""
    return _write_secret(
        f"{_BROKER_CREDENTIALS_PREFIX}/{broker}", credentials, settings=settings or get_settings()
    )


def read_broker_credentials(
    broker: str, *, settings: Settings | None = None
) -> dict[str, str] | None:
    """See `write_broker_credentials` on the `settings` param. Callers (src/brokers/factory.py)
    fall back to `Settings` whether Vault is unreachable or simply has nothing stored yet."""
    return _read_secret(
        f"{_BROKER_CREDENTIALS_PREFIX}/{broker}", settings=settings or get_settings()
    )


def delete_broker_credentials(broker: str, *, settings: Settings | None = None) -> bool:
    """REL-010 E10.8: lets an operator revoke a stored broker credential via the broker-config
    API without needing direct Vault CLI/UI access. See `write_broker_credentials` on the
    `settings` param."""
    return _delete_secret(
        f"{_BROKER_CREDENTIALS_PREFIX}/{broker}", settings=settings or get_settings()
    )


def write_llm_provider_key(
    provider: str, api_key: str, *, settings: Settings | None = None
) -> bool:
    """Same Vault-first pattern as broker credentials (REL-002 E2.2), for LLM provider API keys
    (openai/anthropic/deepseek/gemini/huggingface/opencode -- never "ollama", which needs none).
    See `write_broker_credentials` on the `settings` param."""
    return _write_secret(
        f"{_LLM_PROVIDER_KEYS_PREFIX}/{provider}",
        {"api_key": api_key},
        settings=settings or get_settings(),
    )


def delete_llm_provider_key(provider: str, *, settings: Settings | None = None) -> bool:
    """Removes a provider's stored key entirely -- for tests that write a throwaway key and must
    leave Vault exactly as they found it (not overwritten with a stale value) when the real
    `.env` has no key for that provider to restore."""
    return _delete_secret(
        f"{_LLM_PROVIDER_KEYS_PREFIX}/{provider}", settings=settings or get_settings()
    )


def read_llm_provider_key(provider: str, *, settings: Settings | None = None) -> str | None:
    """Returns the stored API key, or `None` if Vault is unreachable or nothing has been written
    yet for this provider -- callers (src/agents/llm_router.py) fall back to `Settings` in either
    case, indistinguishably, same as broker credentials."""
    stored = _read_secret(
        f"{_LLM_PROVIDER_KEYS_PREFIX}/{provider}", settings=settings or get_settings()
    )
    return stored.get("api_key") if stored else None


def write_mfa_secret(user_id: str, totp_secret: str, *, settings: Settings | None = None) -> bool:
    """REL-007 E7.1 (SEC-014). Uses the same fail-open KV-v2 primitives as everything else in
    this file -- the fail-*closed* posture MFA actually needs (never silently skip a check for
    an enrolled user just because Vault is unreachable) is enforced by the caller
    (src/api/routers/mfa.py), which treats a `None` read as "verification unavailable, 503", not
    "skip MFA". Keeping this helper itself uniform with its siblings avoids two different
    fail-open/fail-closed conventions living in the same module."""
    return _write_secret(
        f"{_MFA_SECRETS_PREFIX}/{user_id}",
        {"totp_secret": totp_secret},
        settings=settings or get_settings(),
    )


def read_mfa_secret(user_id: str, *, settings: Settings | None = None) -> str | None:
    stored = _read_secret(f"{_MFA_SECRETS_PREFIX}/{user_id}", settings=settings or get_settings())
    return stored.get("totp_secret") if stored else None


def delete_mfa_secret(user_id: str, *, settings: Settings | None = None) -> bool:
    return _delete_secret(f"{_MFA_SECRETS_PREFIX}/{user_id}", settings=settings or get_settings())


def write_webhook_secret(
    channel: str, secret: dict[str, str], *, settings: Settings | None = None
) -> bool:
    """REL-007 E7.7 (SEC-028): "shared secrets/app secrets used for signature verification are
    themselves stored in Vault (same KV engine as broker keys), never in application config
    files." `channel` is one of "telegram"/"discord"/"slack"."""
    return _write_secret(
        f"{_WEBHOOK_SECRETS_PREFIX}/{channel}", secret, settings=settings or get_settings()
    )


def read_webhook_secret(channel: str, *, settings: Settings | None = None) -> dict[str, str] | None:
    return _read_secret(f"{_WEBHOOK_SECRETS_PREFIX}/{channel}", settings=settings or get_settings())


def delete_webhook_secret(channel: str, *, settings: Settings | None = None) -> bool:
    return _delete_secret(
        f"{_WEBHOOK_SECRETS_PREFIX}/{channel}", settings=settings or get_settings()
    )


def write_bot_token(channel: str, token: str, *, settings: Settings | None = None) -> bool:
    """REL-010 E10.2: outbound bot credentials (Telegram/Discord), same Vault-first pattern as
    every other secret in this file. Deliberately separate from `write_webhook_secret` -- that
    one holds the INBOUND signature-verification secret (Telegram's secret token, Discord's
    public key), a fundamentally different credential than the OUTBOUND bot token this needs to
    actually *send* a message. `channel` is "telegram" or "discord"."""
    return _write_secret(
        f"{_BOT_TOKENS_PREFIX}/{channel}", {"token": token}, settings=settings or get_settings()
    )


def read_bot_token(channel: str, *, settings: Settings | None = None) -> str | None:
    """Falls back to `Settings` (`.env`-sourced) at the call site, same as every other
    Vault-first read in this file -- returns `None` here whether Vault is unreachable or nothing
    has been written yet, indistinguishably."""
    stored = _read_secret(f"{_BOT_TOKENS_PREFIX}/{channel}", settings=settings or get_settings())
    return stored.get("token") if stored else None


def delete_bot_token(channel: str, *, settings: Settings | None = None) -> bool:
    return _delete_secret(f"{_BOT_TOKENS_PREFIX}/{channel}", settings=settings or get_settings())
