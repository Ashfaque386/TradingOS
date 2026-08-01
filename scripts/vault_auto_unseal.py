"""REL-015 E15.1 (GLH-01): standing auto-unseal daemon for the real (non-dev) Vault server.

Real Vault (file storage backend, `docker/vault/config.hcl`) starts every boot genuinely
"sealed" -- a real security property, not a bug -- and refuses to serve any secret until an
unseal key is submitted. This loop makes that automatic for this single-host, single-operator
environment: on first-ever run it initializes Vault for real (1 key share / 1 key threshold --
see below for why a single share is an accepted simplification here) and saves the unseal key +
root token to a local, gitignored file; on every subsequent run (including after a `vault`
container restart) it reads that same file and unseals automatically, with no human step.

Accepted tradeoff, stated plainly: the unseal key and root token live in a plaintext file on
this host's disk (`/app/vault/keys/`). This is the same "if someone can read this host's disk,
they have your secrets" exposure every other secret in this single-operator dev-as-production
environment already has (docker-compose.yml's own Postgres/JWT dev passwords, the `.env` file)
-- not a new category of risk, and proportionate to running Vault unattended on a single host
with no cloud KMS/auto-unseal mechanism available. A real multi-operator or cloud deployment
would use a real auto-unseal mechanism (AWS KMS, Transit auto-unseal from a second Vault, etc.)
instead of this file -- out of scope for the single-host model this project has adopted
(Phase 1 ADR 10).

Single key share (not Shamir's traditional 5-share/3-threshold split): with exactly one human
operator, splitting the unseal key across multiple shares held by different people has no one to
distribute them to -- it would only mean this same script needs to read multiple key files
instead of one, with no real security improvement. Documented here as a deliberate
simplification, not an oversight.
"""

import logging
import time
from pathlib import Path

import hvac

from src.core.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("vault_auto_unseal")

KEYS_DIR = Path("/app/vault/keys")
UNSEAL_KEY_PATH = KEYS_DIR / "unseal_key"
ROOT_TOKEN_PATH = KEYS_DIR / "root_token"

POLL_INTERVAL_SECONDS = 5


def _initialize(client: hvac.Client) -> None:
    logger.info(
        "Vault is not initialized -- performing real first-time initialization "
        "(1 key share/threshold, see module docstring)."
    )
    result = client.sys.initialize(secret_shares=1, secret_threshold=1)
    unseal_key = result["keys"][0]
    root_token = result["root_token"]

    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    UNSEAL_KEY_PATH.write_text(unseal_key, encoding="utf-8")
    ROOT_TOKEN_PATH.write_text(root_token, encoding="utf-8")
    UNSEAL_KEY_PATH.chmod(0o600)
    ROOT_TOKEN_PATH.chmod(0o600)
    logger.info(
        "Vault initialized for real -- unseal key + root token saved to %s (never logged).",
        KEYS_DIR,
    )


def _unseal(client: hvac.Client) -> None:
    if not UNSEAL_KEY_PATH.exists():
        logger.error(
            "Vault is sealed but no saved unseal key exists at %s -- cannot auto-unseal.",
            UNSEAL_KEY_PATH,
        )
        return
    unseal_key = UNSEAL_KEY_PATH.read_text(encoding="utf-8").strip()
    client.sys.submit_unseal_key(unseal_key)
    logger.info("Vault unsealed for real using the saved key.")


def run_once() -> None:
    settings = get_settings()
    client = hvac.Client(url=settings.vault_addr or "http://vault:8200")

    if not client.sys.is_initialized():
        _initialize(client)

    # A freshly-initialized Vault is still sealed until a key is submitted -- initialize() and
    # unseal() are always two separate real steps, even on the very first run.
    if client.sys.is_sealed():
        _unseal(client)


def main() -> None:
    logger.info(
        "Vault auto-unseal daemon starting (REL-015 E15.1) -- polling every %ss.",
        POLL_INTERVAL_SECONDS,
    )
    while True:
        try:
            run_once()
        except Exception as exc:  # noqa: BLE001 -- must never crash this standing loop
            logger.warning("Vault auto-unseal check failed (will retry): %s", exc)
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
