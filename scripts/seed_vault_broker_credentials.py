"""Pushes the currently-configured broker credentials (read from `.env`/Settings, the same way
they've been managed all along) into the local dev Vault (src/core/vault.py). Run once per
environment or whenever a broker token is refreshed, via
`docker exec tradingos-app python scripts/seed_vault_broker_credentials.py`.

After this runs, src/brokers/factory.py's adapters are built from Vault instead of directly
from `.env` -- a real Vault-issued-credential retrieval path (Phase 4 E4.1 exit criterion), not
just a copy sitting unused. `.env` remains the fallback if Vault is ever unreachable or a
broker's Vault entry is missing, so nothing breaks if this script hasn't been run yet.
"""

from src.core import vault
from src.core.config import get_settings


def main() -> None:
    settings = get_settings()
    wrote_any = False

    if settings.zerodha_api_key and settings.zerodha_access_token:
        ok = vault.write_broker_credentials(
            "zerodha",
            {"api_key": settings.zerodha_api_key, "access_token": settings.zerodha_access_token},
        )
        print(f"Zerodha credentials {'written to' if ok else 'FAILED to write to'} Vault.")
        wrote_any = wrote_any or ok
    else:
        print("Zerodha not configured in .env -- nothing to seed for it.")

    if settings.upstox_access_token:
        ok = vault.write_broker_credentials(
            "upstox",
            {
                "access_token": settings.upstox_access_token,
                "use_sandbox": str(settings.upstox_use_sandbox),
            },
        )
        print(f"Upstox credentials {'written to' if ok else 'FAILED to write to'} Vault.")
        wrote_any = wrote_any or ok
    else:
        print("Upstox not configured in .env -- nothing to seed for it.")

    if not wrote_any:
        print(
            "WARNING: nothing was written to Vault -- either no broker is configured in .env, "
            "or Vault is unreachable (check VAULT_ADDR/VAULT_TOKEN and that the `vault` "
            "container is running)."
        )


if __name__ == "__main__":
    main()
