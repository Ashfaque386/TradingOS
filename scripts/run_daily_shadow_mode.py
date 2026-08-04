"""Runs one real Shadow Mode attempt against each configured broker (Phase 4 Epic E4.4 exit
criterion: the 5-consecutive-clean-day streak, Phase_9_Master_Implementation_Guide.md §4/§6).
Meant to run once per real trading day -- see the project's Phase_14_Master_Development_Roadmap.md
for how "going forward" recurrence is actually scheduled, since no in-app scheduler exists yet
and standing up an OS-level recurring task is a separate, explicit decision, not something this
script does on its own.

Calls the real, already-running FastAPI app over HTTP (not the internal Python functions
directly), so this exercises exactly the same path a real recurring job would hit --
src/api/routers/shadow_mode.py's real request/response cycle, a real Postgres write, nothing
bypassed. Run via `docker exec tradingos-app python scripts/run_daily_shadow_mode.py`.

Real regression, found and fixed here (2026-08-04): REL-013's SEC-046 fix correctly closed a
zero-auth gap on `/shadow-mode/attempt` (it now requires SystemAdministrator/PortfolioManager/
RiskManager), but this script was never updated to send a token -- it has been getting a real
401 "Not authenticated" and silently failing every single day since (no error surfaced anywhere
the Windows Scheduled Task's own output goes; `logs/shadow_mode_daily.log` just stopped
growing), stalling the real go-live clean-day streak with zero visibility. `_authenticate()`
below does a real login (same `ADMIN_BOOTSTRAP_EMAIL`/`ADMIN_BOOTSTRAP_PASSWORD` credentials
`scripts/seed_admin_user.py` already uses) and attaches the resulting access token as a real
Bearer header -- MFA is not mandatory for any role today (REL-014's own documented decision), so
a plain login genuinely returns a usable token here, not a `mfa_required` challenge.

The `symbol` the API expects is broker-format-specific, not something Shadow Mode itself
resolves (its job is just to dispatch whatever symbol it's given to the named broker's real
adapter -- src/brokers/shadow_mode.py). Zerodha's `KiteConnectAdapter.build_order_payload`
wants a plain NSE tradingsymbol ("INFY"); Upstox's `place_order` wants an already-resolved
`instrument_key` ("NSE_EQ|INE..."), confirmed by a real 400 Bad Request the first time this
script ran with a bare symbol for Upstox -- so this script resolves Upstox's instrument_key for
real before calling the API, same as every other real Upstox order in this codebase does.
"""

import asyncio
import os
import sys

import httpx

from src.brokers.factory import NoBrokerConfigured, build_upstox_adapter

APP_BASE_URL = "http://localhost:8000"
SYMBOL = "INFY"
ADMIN_EMAIL = os.environ.get("ADMIN_BOOTSTRAP_EMAIL", "admin@tradingos.local")
ADMIN_PASSWORD = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD", "dev-only-change-me")


async def _resolve_upstox_symbol() -> str | None:
    try:
        adapter = build_upstox_adapter()
    except NoBrokerConfigured:
        return None
    async with adapter:
        return await adapter.search_instrument_key(SYMBOL)


def _authenticate() -> str:
    response = httpx.post(
        f"{APP_BASE_URL}/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15.0,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("mfa_required"):
        raise RuntimeError(
            "Login requires MFA -- this script has no interactive way to supply a TOTP code. "
            "Either MFA_MANDATORY_ROLES now includes this account's role (a real config change "
            "since this script was last verified), or the account was individually enrolled."
        )
    access_token: str = body["access_token"]
    return access_token


def main() -> None:
    try:
        access_token = _authenticate()
    except (httpx.HTTPError, RuntimeError, KeyError) as exc:
        print(f"Authentication failed -- cannot run any Shadow Mode attempts: {exc}")
        sys.exit(1)
    auth_headers = {"Authorization": f"Bearer {access_token}"}

    upstox_symbol = asyncio.run(_resolve_upstox_symbol())
    broker_symbols = {"zerodha": SYMBOL, "upstox": upstox_symbol}

    for broker, symbol in broker_symbols.items():
        if symbol is None:
            print(f"{broker}: not configured, skipped")
            continue
        try:
            response = httpx.post(
                f"{APP_BASE_URL}/api/v1/shadow-mode/attempt",
                json={"broker": broker, "symbol": symbol, "side": "BUY", "quantity": 1},
                headers=auth_headers,
                timeout=15.0,
            )
        except httpx.HTTPError as exc:
            print(f"{broker}: request failed -- {exc}")
            continue

        if response.status_code == 503:
            print(f"{broker}: not configured, skipped ({response.json()['detail']})")
            continue
        if response.status_code != 201:
            print(f"{broker}: unexpected status {response.status_code} -- {response.text[:200]}")
            continue

        body = response.json()
        print(
            f"{broker}: {body['outcome']} "
            f"(used_real_sandbox={body['used_real_sandbox']}, latency={body['latency_ms']:.1f}ms)"
        )

    status = httpx.get(
        f"{APP_BASE_URL}/api/v1/shadow-mode/status", headers=auth_headers, timeout=10.0
    ).json()
    print(
        f"\nConsecutive clean days: {status['consecutive_clean_days']} "
        f"(go-live gate met: {status['go_live_gate_met']})"
    )


if __name__ == "__main__":
    main()
