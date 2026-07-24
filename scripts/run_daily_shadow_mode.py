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

The `symbol` the API expects is broker-format-specific, not something Shadow Mode itself
resolves (its job is just to dispatch whatever symbol it's given to the named broker's real
adapter -- src/brokers/shadow_mode.py). Zerodha's `KiteConnectAdapter.build_order_payload`
wants a plain NSE tradingsymbol ("INFY"); Upstox's `place_order` wants an already-resolved
`instrument_key` ("NSE_EQ|INE..."), confirmed by a real 400 Bad Request the first time this
script ran with a bare symbol for Upstox -- so this script resolves Upstox's instrument_key for
real before calling the API, same as every other real Upstox order in this codebase does.
"""

import asyncio

import httpx

from src.brokers.factory import NoBrokerConfigured, build_upstox_adapter

APP_BASE_URL = "http://localhost:8000"
SYMBOL = "INFY"


async def _resolve_upstox_symbol() -> str | None:
    try:
        adapter = build_upstox_adapter()
    except NoBrokerConfigured:
        return None
    async with adapter:
        return await adapter.search_instrument_key(SYMBOL)


def main() -> None:
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

    status = httpx.get(f"{APP_BASE_URL}/api/v1/shadow-mode/status", timeout=10.0).json()
    print(
        f"\nConsecutive clean days: {status['consecutive_clean_days']} "
        f"(go-live gate met: {status['go_live_gate_met']})"
    )


if __name__ == "__main__":
    main()
