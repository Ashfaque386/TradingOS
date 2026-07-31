"""One-off manual Zerodha Kite Connect daily token refresh.

Kite's access token expires daily (~6 AM IST, no refresh token) -- this exchanges a fresh
`request_token` (obtained by logging in via https://kite.zerodha.com/connect/login?api_key=...
and copying it off the redirect URL) for a real access_token via POST
https://api.kite.trade/session/token, per src/core/config.py's own documented flow, then
writes it to the real dev Vault (same path src/brokers/factory.py already reads from).

Usage: python scripts/refresh_zerodha_token.py <request_token>
Never prints the access_token or api_secret to stdout/logs.
"""

import hashlib
import sys

import httpx

from src.core import vault
from src.core.config import get_settings


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/refresh_zerodha_token.py <request_token>")
        return 1
    request_token = sys.argv[1]

    settings = get_settings()
    if not settings.zerodha_api_key or not settings.zerodha_api_secret:
        print("zerodha_api_key/zerodha_api_secret not configured in Settings.")
        return 1

    checksum = hashlib.sha256(
        (settings.zerodha_api_key + request_token + settings.zerodha_api_secret).encode()
    ).hexdigest()

    response = httpx.post(
        "https://api.kite.trade/session/token",
        data={
            "api_key": settings.zerodha_api_key,
            "request_token": request_token,
            "checksum": checksum,
        },
        timeout=10.0,
    )
    if response.status_code != 200:
        print(f"Token exchange failed: {response.status_code} {response.text[:300]}")
        return 1

    access_token = response.json()["data"]["access_token"]

    ok = vault.write_broker_credentials(
        "zerodha", {"api_key": settings.zerodha_api_key, "access_token": access_token}
    )
    if ok:
        print("Real access_token exchanged and written to Vault (broker-credentials/zerodha).")
        return 0

    print("Vault write failed -- access_token exchanged successfully but NOT persisted.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
