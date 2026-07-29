"""Pushes the currently-configured webhook platform secrets (read from `.env`/Settings) into
the local dev Vault (src/core/vault.py). Run once per environment or whenever a platform secret
is rotated, via `docker exec tradingos-app python scripts/seed_vault_webhook_secrets.py`.

After this runs, src/api/routers/webhooks.py reads these from Vault instead of directly from
`.env` -- same Vault-first, `.env`-fallback pattern as
scripts/seed_vault_broker_credentials.py/seed_vault_llm_keys.py.
"""

from src.core import vault
from src.core.config import get_settings


def main() -> None:
    settings = get_settings()
    wrote_any = False

    if settings.telegram_webhook_secret:
        ok = vault.write_webhook_secret(
            "telegram", {"secret_token": settings.telegram_webhook_secret}
        )
        print(f"Telegram webhook secret {'written to' if ok else 'FAILED to write to'} Vault.")
        wrote_any = wrote_any or ok
    else:
        print("TELEGRAM_WEBHOOK_SECRET not configured in .env -- nothing to seed for it.")

    if settings.discord_public_key:
        ok = vault.write_webhook_secret("discord", {"public_key": settings.discord_public_key})
        print(f"Discord public key {'written to' if ok else 'FAILED to write to'} Vault.")
        wrote_any = wrote_any or ok
    else:
        print("DISCORD_PUBLIC_KEY not configured in .env -- nothing to seed for it.")

    if settings.whatsapp_app_secret:
        ok = vault.write_webhook_secret("whatsapp", {"app_secret": settings.whatsapp_app_secret})
        print(f"WhatsApp app secret {'written to' if ok else 'FAILED to write to'} Vault.")
        wrote_any = wrote_any or ok
    else:
        print("WHATSAPP_APP_SECRET not configured in .env -- nothing to seed for it.")

    if not wrote_any:
        print(
            "WARNING: nothing was written to Vault -- either no webhook platform is configured "
            "in .env, or Vault is unreachable (check VAULT_ADDR/VAULT_TOKEN and that the "
            "`vault` container is running)."
        )


if __name__ == "__main__":
    main()
