"""REL-015 E15.4 (GLH-11): the honest conclusion of researching broker-token-refresh automation
is that it CANNOT be legitimately automated for either broker -- both require a real, interactive
human login (username/password + 2FA) each trading day, by deliberate design on the broker's own
side, not a technical gap in this codebase:

  - Zerodha Kite Connect: access token expires ~6 AM IST daily, no refresh token
    (src/core/config.py's own zerodha_* field comments).
  - Upstox: access token expires ~3:30 AM IST daily, no refresh token
    (src/core/config.py's own upstox_* field comments).

Scripting around the login page itself (headless browser + stored password/TOTP seed) would (a)
require storing far more sensitive material than the API key/secret this system currently holds,
and (b) very likely violate both brokers' Terms of Service, which exist specifically to require a
human in the loop for this exact reason. This is documented here as a permanent operational
constraint, not tracked as an open "not yet automated" item -- see the Go-Live Hardening
Checklist (GLH-11).

What this script DOES do -- the honest, real reduction of manual friction: one interactive prompt
per broker instead of two separate scripts (refresh_zerodha_token.py + sync_zerodha_token_to_env.py)
plus manually parsing a redirect URL by eye. Paste the FULL redirect URL you land on after logging
in; this extracts the token, exchanges it for a real access_token, and writes it to Vault (and,
for Zerodha, syncs .env too, since some tests read from there directly). Never prints a token/
secret to stdout.

Usage (inside the running container): python scripts/daily_broker_login_helper.py [zerodha|upstox]
No argument runs whichever brokers are configured.
"""

import hashlib
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from src.core import vault
from src.core.config import get_settings

ENV_PATH = Path("/app/.env")


def _extract_param(pasted: str, param: str) -> str | None:
    """Accepts either the bare token/code or the full redirect URL -- a user pasting the whole
    address bar contents is the common case, but the raw value alone also works. A pasted value
    that has a query string but doesn't contain `param` is a real miss (e.g. the wrong redirect
    was pasted) -- it must return None, not silently treat the whole URL as the token."""
    pasted = pasted.strip()
    parsed = urlparse(pasted)
    if parsed.query:
        values = parse_qs(parsed.query).get(param)
        return values[0] if values else None
    return pasted or None


def _sync_zerodha_env(access_token: str) -> None:
    if not ENV_PATH.exists():
        return
    text = ENV_PATH.read_text(encoding="utf-8")
    new_text, count = re.subn(
        r"^ZERODHA_ACCESS_TOKEN=.*$",
        f"ZERODHA_ACCESS_TOKEN={access_token}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if count == 1:
        ENV_PATH.write_text(new_text, encoding="utf-8")
        print("  .env ZERODHA_ACCESS_TOKEN line updated too.")


def _refresh_zerodha() -> int:
    settings = get_settings()
    if not settings.zerodha_api_key or not settings.zerodha_api_secret:
        print("Zerodha not configured (zerodha_api_key/zerodha_api_secret unset) -- skipping.")
        return 0

    login_url = f"https://kite.zerodha.com/connect/login?api_key={settings.zerodha_api_key}&v=3"
    print(
        f"\nZerodha: open this URL, log in, then paste the FULL redirect URL below:\n  {login_url}"
    )
    pasted = input("Redirect URL (or just the request_token): ").strip()
    request_token = _extract_param(pasted, "request_token")
    if not request_token:
        print("Could not find a request_token in what was pasted -- skipping Zerodha.")
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
        print(f"Zerodha token exchange failed: {response.status_code} {response.text[:300]}")
        return 1

    access_token = response.json()["data"]["access_token"]
    ok = vault.write_broker_credentials(
        "zerodha", {"api_key": settings.zerodha_api_key, "access_token": access_token}
    )
    if not ok:
        print("Zerodha: Vault write failed -- token exchanged but NOT persisted.")
        return 1
    print("Zerodha: real access_token exchanged and written to Vault.")
    _sync_zerodha_env(access_token)
    return 0


def _refresh_upstox() -> int:
    settings = get_settings()
    if (
        not settings.upstox_api_key
        or not settings.upstox_api_secret
        or not settings.upstox_redirect_uri
    ):
        print("Upstox not configured (upstox_api_key/api_secret/redirect_uri unset) -- skipping.")
        return 0

    login_url = (
        "https://api.upstox.com/v2/login/authorization/dialog"
        f"?response_type=code&client_id={settings.upstox_api_key}"
        f"&redirect_uri={settings.upstox_redirect_uri}"
    )
    print(
        f"\nUpstox: open this URL, log in, then paste the FULL redirect URL below:\n  {login_url}"
    )
    pasted = input("Redirect URL (or just the code): ").strip()
    code = _extract_param(pasted, "code")
    if not code:
        print("Could not find a code in what was pasted -- skipping Upstox.")
        return 1

    # Upstox v2's documented OAuth2 authorization_code grant -- not independently re-verified
    # against a live account by this change (no Upstox production credentials available here);
    # verify against a real account before relying on this daily.
    response = httpx.post(
        "https://api.upstox.com/v2/login/authorization/token",
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        data={
            "code": code,
            "client_id": settings.upstox_api_key,
            "client_secret": settings.upstox_api_secret,
            "redirect_uri": settings.upstox_redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=10.0,
    )
    if response.status_code != 200:
        print(f"Upstox token exchange failed: {response.status_code} {response.text[:300]}")
        return 1

    access_token = response.json()["access_token"]
    ok = vault.write_broker_credentials(
        "upstox", {"api_key": settings.upstox_api_key, "access_token": access_token}
    )
    if not ok:
        print("Upstox: Vault write failed -- token exchanged but NOT persisted.")
        return 1
    print("Upstox: real access_token exchanged and written to Vault.")
    return 0


def main() -> int:
    which = sys.argv[1].lower() if len(sys.argv) > 1 else "both"
    exit_code = 0
    if which in ("zerodha", "both"):
        exit_code |= _refresh_zerodha()
    if which in ("upstox", "both"):
        exit_code |= _refresh_upstox()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
