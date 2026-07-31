"""Copies the just-refreshed Zerodha access_token from Vault into .env's
ZERODHA_ACCESS_TOKEN= line, in place. tests/integration/test_kite_connect_live.py constructs
KiteConnectAdapter directly from Settings (not via src/brokers/factory.py's Vault-first path),
so Vault alone isn't enough to make those tests see a freshly refreshed token -- .env is the
source those specific tests read from. Never prints the token to stdout/logs.
"""

import re
from pathlib import Path

from src.core import vault
from src.core.config import get_settings

ENV_PATH = Path("/app/.env")


def main() -> int:
    settings = get_settings()
    stored = vault.read_broker_credentials("zerodha")
    if not stored or not stored.get("access_token"):
        print("No zerodha access_token found in Vault -- run refresh_zerodha_token.py first.")
        return 1

    text = ENV_PATH.read_text(encoding="utf-8")
    new_text, count = re.subn(
        r"^ZERODHA_ACCESS_TOKEN=.*$",
        f"ZERODHA_ACCESS_TOKEN={stored['access_token']}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        print("Could not find a ZERODHA_ACCESS_TOKEN= line in .env to replace.")
        return 1

    ENV_PATH.write_text(new_text, encoding="utf-8")
    print("ZERODHA_ACCESS_TOKEN line in .env updated from Vault's stored value.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
