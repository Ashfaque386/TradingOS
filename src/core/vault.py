"""Local dev Vault client (Phase 4 E4.1 exit criterion: "Wire Vault-issued short-lived tokens
for broker API key retrieval at execution time", Phase 3 §5 sequence diagram). Talks to the
real dev-mode Vault instance in docker-compose.yml's `vault` service via HashiCorp's official
`hvac` client -- a genuine KV v2 read/write round-trip against a real server, not a stub.

Scope, deliberately reduced from the full Phase_12_Security_Design.md §3 design:
  - Storage backend is Vault dev mode's in-memory store, not a real durable backend (Consul/
    Raft) -- restarting the `vault` container loses everything written to it, by design.
  - No auto-unseal, no TLS, a fixed root token baked into docker-compose.yml -- fine for a local
    container on a dev machine, never acceptable for production.
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
from typing import cast

import hvac

from src.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_KV_MOUNT = "secret"
_BROKER_CREDENTIALS_PREFIX = "broker-credentials"
_LLM_PROVIDER_KEYS_PREFIX = "llm-provider-keys"
_MFA_SECRETS_PREFIX = "mfa-secrets"
_WEBHOOK_SECRETS_PREFIX = "webhook-secrets"


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
    files." `channel` is one of "telegram"/"discord"/"whatsapp"."""
    return _write_secret(
        f"{_WEBHOOK_SECRETS_PREFIX}/{channel}", secret, settings=settings or get_settings()
    )


def read_webhook_secret(channel: str, *, settings: Settings | None = None) -> dict[str, str] | None:
    return _read_secret(f"{_WEBHOOK_SECRETS_PREFIX}/{channel}", settings=settings or get_settings())


def delete_webhook_secret(channel: str, *, settings: Settings | None = None) -> bool:
    return _delete_secret(
        f"{_WEBHOOK_SECRETS_PREFIX}/{channel}", settings=settings or get_settings()
    )
