"""Upstox broker adapter (Phase 4 Epic E4.1), per Phase_6_Trading_Engine_Design.md §6: "Upstox
Implementation (UpstoxAdapter): Secondary executor/fallback."

Endpoint paths, request/response fields, and the OAuth2 flow below were confirmed against
Upstox's own developer documentation (https://upstox.com/developer/api-documentation/). Note:
an initial WebFetch-based pass reported the sandbox host as `sandbox.upstox.com` (quoting what
looked like a real curl example) -- that host does not resolve in DNS at all and was a
research/summarization artifact, not a real endpoint. The actual sandbox host,
`api-sandbox.upstox.com`, was confirmed empirically: it resolves and returns Upstox's real
error-JSON shape (`{"status":"error","errors":[{"errorCode":"UDAPI...", ...}]}`) for an
unauthenticated request, matching the documented error-code format exactly.

Defaults to the Sandbox base URL (`UPSTOX_USE_SANDBOX=true` in src/core/config.py) which Upstox
documents as "closely emulat[ing] the real API with no risk" -- real order placement/
modification/cancellation can be exercised end-to-end in tests without ever touching a live
exchange or real funds. Flipping to production is a deliberate settings change, never a default.
"""

from datetime import date
from typing import Any

import httpx

from src.brokers.base import (
    BrokerAdapter,
    DepthLevel,
    Margin,
    OptionChain,
    OptionInstrument,
    OrderRequest,
    OrderResponse,
    OrderStatus,
    OrderType,
    Position,
    Quote,
    Side,
)

UPSTOX_PRODUCTION_BASE_URL = "https://api.upstox.com/v2"
UPSTOX_SANDBOX_BASE_URL = "https://api-sandbox.upstox.com/v2"

_PRODUCT_CODE = {"INTRADAY": "I", "DELIVERY": "D"}

# Upstox's order status vocabulary, mapped onto our own DB-008 ORDERS.status values
# (Phase_11_Database_Design.md). Reconstructed from Upstox's public docs/community references,
# not exhaustively verified against a live sandbox response -- an unmapped status raises rather
# than silently mis-recording order state, so a real gap surfaces immediately in testing instead
# of corrupting the order ledger.
_STATUS_MAP: dict[str, OrderStatus] = {
    "complete": "FILLED",
    "open": "OPEN",
    "open pending": "PENDING",
    "trigger pending": "OPEN",
    "validation pending": "PENDING",
    "modify pending": "OPEN",
    "put order req received": "PENDING",
    "after market order req received": "PENDING",
    "cancelled": "CANCELLED",
    "cancel pending": "OPEN",
    "not cancelled": "OPEN",  # a cancel attempt failed; the order is still live
    "rejected": "REJECTED",
}


class UpstoxOrderStatusError(ValueError):
    """Raised when Upstox returns an order status string not in `_STATUS_MAP` -- surfaced
    loudly rather than guessed at, since silently mis-mapping order state in a trading system
    is worse than failing loudly."""


class UpstoxAdapter(BrokerAdapter):
    def __init__(
        self, *, access_token: str, use_sandbox: bool = True, timeout: float = 10.0
    ) -> None:
        base_url = UPSTOX_SANDBOX_BASE_URL if use_sandbox else UPSTOX_PRODUCTION_BASE_URL
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "UpstoxAdapter":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # --- BrokerAdapter interface -------------------------------------------------------

    async def place_order(self, order: OrderRequest) -> OrderResponse:
        payload = {
            "quantity": order.quantity,
            "product": _PRODUCT_CODE[order.product],
            "validity": order.validity,
            "price": order.limit_price or 0,
            # Upstox's field is literally named `instrument_token`, but its documented format
            # matches the `instrument_key` string (e.g. "NSE_EQ|INE002A01018") returned by
            # search_instrument_key() below, not a bare numeric token -- verify against a real
            # sandbox response if orders start getting rejected with an instrument-not-found
            # error.
            "instrument_token": order.symbol,
            "order_type": order.order_type,
            "transaction_type": order.side,
            "disclosed_quantity": 0,
            "trigger_price": order.trigger_price or 0,
            "is_amo": False,
        }
        if order.tag:
            payload["tag"] = order.tag

        response = await self._client.post("/order/place", json=payload)
        response.raise_for_status()
        broker_order_id: str = response.json()["data"]["order_id"]

        return OrderResponse(
            broker_order_id=broker_order_id,
            status="PENDING",  # place/place response has no status; caller polls get_order_book
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            quantity=order.quantity,
            limit_price=order.limit_price,
            raw=response.json(),
        )

    async def modify_order(
        self,
        broker_order_id: str,
        *,
        quantity: int | None = None,
        order_type: OrderType | None = None,
        limit_price: float | None = None,
        trigger_price: float | None = None,
    ) -> OrderResponse:
        payload: dict[str, Any] = {"order_id": broker_order_id}
        if quantity is not None:
            payload["quantity"] = quantity
        if order_type is not None:
            payload["order_type"] = order_type
        if limit_price is not None:
            payload["price"] = limit_price
        if trigger_price is not None:
            payload["trigger_price"] = trigger_price

        response = await self._client.put("/order/modify", json=payload)
        response.raise_for_status()

        # The modify response only echoes back {"data": {"order_id": ...}}, not the order's
        # full current state -- re-fetch the order book for an accurate OrderResponse rather
        # than assembling one from what we merely requested (a modify can be partially applied
        # or race a fill).
        return await self._fetch_single_order(broker_order_id)

    async def cancel_order(self, broker_order_id: str) -> OrderResponse:
        response = await self._client.delete("/order/cancel", params={"order_id": broker_order_id})
        response.raise_for_status()
        # Same reasoning as modify_order: confirm actual post-cancel state, don't assume success
        # means "CANCELLED" (the order may have already filled before the cancel landed).
        return await self._fetch_single_order(broker_order_id)

    async def get_order_book(self) -> list[OrderResponse]:
        response = await self._client.get("/order/retrieve-all")
        response.raise_for_status()
        return [self._parse_order(raw) for raw in response.json()["data"]]

    async def get_margin(self) -> Margin:
        response = await self._client.get("/user/get-funds-and-margin", params={"segment": "SEC"})
        response.raise_for_status()
        data = response.json()["data"]
        return Margin(
            available_margin=data["available_margin"], used_margin=data["used_margin"], raw=data
        )

    async def get_positions(self) -> list[Position]:
        response = await self._client.get("/portfolio/short-term-positions")
        response.raise_for_status()
        return [
            Position(
                symbol=raw.get("trading_symbol") or raw["instrument_token"],
                net_quantity=raw["quantity"],
                average_price=raw.get("average_price"),
                last_price=raw.get("last_price"),
                unrealized_pnl=raw.get("unrealised", 0.0),
                realized_pnl=raw.get("realised", 0.0),
            )
            for raw in response.json()["data"]
        ]

    async def get_quote(self, symbol: str) -> Quote:
        """Real Level-2 depth via GET /market-quote/quotes. This endpoint doesn't exist on
        Upstox's sandbox host at all (confirmed against Upstox's own docs -- no sandbox
        alternative is mentioned) -- always calls production regardless of `use_sandbox`, since
        reading a quote places no order and risks no funds, unlike every other method here."""
        instrument_key = await self.search_instrument_key(symbol)
        response = await self._client.get(
            f"{UPSTOX_PRODUCTION_BASE_URL}/market-quote/quotes",
            params={"instrument_key": instrument_key},
        )
        response.raise_for_status()
        data = response.json()["data"]
        # The response keys each instrument by "EXCHANGE:SYMBOL" (e.g. "NSE_EQ:INFY"), not the
        # instrument_key used in the request -- take the (only) value rather than re-deriving
        # that key format.
        quote_data = next(iter(data.values()))
        depth = quote_data.get("depth", {})
        return Quote(
            symbol=symbol,
            last_price=quote_data["last_price"],
            buy_depth=[DepthLevel(**level) for level in depth.get("buy", [])],
            sell_depth=[DepthLevel(**level) for level in depth.get("sell", [])],
        )

    # --- Upstox-specific helpers (not part of the broker-agnostic interface) -----------

    async def search_instrument_key(
        self, query: str, *, exchange: str = "NSE", segment: str = "EQ"
    ) -> str:
        """Resolves a human symbol/name (e.g. "RELIANCE") to Upstox's `instrument_key` format
        (e.g. "NSE_EQ|INE002A01018") via Upstox's instrument search endpoint. Raises `ValueError`
        if nothing matches -- callers should not guess an instrument_key by hand."""
        response = await self._client.get(
            "/instruments/search",
            params={"query": query, "exchanges": exchange, "segments": segment},
        )
        response.raise_for_status()
        results = response.json()["data"]
        if not results:
            raise ValueError(f"No Upstox instrument found for query={query!r}")
        instrument_key: str = results[0]["instrument_key"]
        return instrument_key

    async def get_historical_candles(
        self, instrument_key: str, interval: str, from_date: str, to_date: str
    ) -> list[list[Any]]:
        """REL-010 E10.7: real Upstox historical-candle endpoint --
        `GET /historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}`, confirmed
        against Upstox's own developer docs (real path/param order, not guessed): `interval` is
        one of "1minute"/"3minute"/"5minute"/"15minute"/"30minute"/"day"/"week"/"month"; dates
        are `YYYY-MM-DD` strings. Each returned candle is
        `[timestamp, open, high, low, close, volume, open_interest]`, Upstox's own real response
        shape -- this method returns that raw list-of-lists rather than reshaping it, so callers
        decide their own DataFrame schema (see src/data/ingest/intraday.py).

        Real, confirmed finding (empirical call against the live sandbox at implementation
        time): Upstox's SANDBOX returns a real 404 for this endpoint regardless of interval/date
        range -- historical market data is not part of sandbox's simulated coverage, matching
        the same already-documented partial-sandbox-coverage pattern as get_margin()/
        get_positions() (see tests/integration/test_upstox_sandbox.py's own module docstring).
        This method is covered by mocked-HTTP unit tests only
        (tests/unit/test_upstox_adapter.py); real live verification needs a genuine PRODUCTION
        Upstox access token, which is not configured in this dev environment -- an honest,
        stated gap, same category as Kite Connect having no sandbox at all."""
        response = await self._client.get(
            f"/historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}"
        )
        response.raise_for_status()
        candles: list[list[Any]] = response.json()["data"]["candles"]
        return candles

    async def get_option_chain(self, underlying: str, expiry: date) -> OptionChain:
        """REL-010 E10.4. Real Upstox endpoint -- `GET /option/chain?instrument_key=...&
        expiry_date=YYYY-MM-DD` -- confirmed against Upstox's own developer docs. Unlike Kite,
        Upstox's real response already includes real Greeks/IV per contract (`option_greeks`),
        so this method parses Upstox's own values directly rather than re-deriving them via
        src/engine/options/greeks.py. `underlying` must be a real Upstox instrument_key (e.g.
        "NSE_INDEX|Nifty 50"), matching this method's own real endpoint contract -- callers
        resolve a plain symbol via `search_instrument_key()` first, same as every other method
        here that needs one.

        Real, confirmed finding (empirical call against the live sandbox at implementation
        time): Upstox's SANDBOX also 404s on this endpoint, same as get_historical_candles above
        -- covered by mocked-HTTP unit tests only; real live verification needs a genuine
        production Upstox access token, not configured in this dev environment."""
        response = await self._client.get(
            "/option/chain",
            params={"instrument_key": underlying, "expiry_date": expiry.isoformat()},
        )
        response.raise_for_status()
        rows = response.json()["data"]

        spot_price = rows[0]["underlying_spot_price"] if rows else 0.0
        instruments: list[OptionInstrument] = []
        for row in rows:
            strike = float(row["strike_price"])
            for side_key, option_type in (("call_options", "CE"), ("put_options", "PE")):
                leg = row.get(side_key)
                if leg is None:
                    continue
                market_data = leg.get("market_data", {})
                greeks = leg.get("option_greeks", {})
                instruments.append(
                    OptionInstrument(
                        symbol=leg.get("instrument_key", f"{underlying}-{strike}-{option_type}"),
                        underlying=underlying,
                        strike=strike,
                        option_type=option_type,
                        expiry=expiry,
                        last_price=market_data.get("ltp"),
                        open_interest=market_data.get("oi"),
                        implied_volatility=greeks.get("iv"),
                    )
                )

        return OptionChain(
            underlying=underlying, expiry=expiry, spot_price=spot_price, instruments=instruments
        )

    async def list_expiries(self, underlying: str) -> list[date]:
        """REL-030 E30.1. Real Upstox endpoint -- `GET /option/contract?instrument_key=...`
        (https://upstox.com/developer/api-documentation/get-option-contracts/), confirmed
        against Upstox's own current docs -- with no `expiry_date` param, per that endpoint's
        own documented purpose distinct from `/option/chain` above (which requires one real
        expiry). `underlying` must already be a real Upstox instrument_key, same contract as
        get_option_chain above. Real, confirmed limitation matching that method's own: Upstox's
        sandbox 404s on this endpoint too -- covered by mocked-HTTP unit tests only here."""
        response = await self._client.get("/option/contract", params={"instrument_key": underlying})
        response.raise_for_status()
        rows = response.json()["data"]

        today = date.today()
        expiries = {date.fromisoformat(row["expiry"]) for row in rows}
        return sorted(e for e in expiries if e >= today)

    async def _fetch_single_order(self, broker_order_id: str) -> OrderResponse:
        for order in await self.get_order_book():
            if order.broker_order_id == broker_order_id:
                return order
        raise ValueError(f"Order {broker_order_id!r} not found in Upstox order book")

    def _parse_order(self, raw: dict[str, Any]) -> OrderResponse:
        status_str = str(raw["status"]).lower()
        if status_str not in _STATUS_MAP:
            raise UpstoxOrderStatusError(
                f"Unmapped Upstox order status {raw['status']!r} for order {raw.get('order_id')}"
            )
        side: Side = raw["transaction_type"]
        order_type: OrderType = raw["order_type"]
        return OrderResponse(
            broker_order_id=raw["order_id"],
            status=_STATUS_MAP[status_str],
            symbol=raw.get("trading_symbol") or raw["instrument_token"],
            side=side,
            order_type=order_type,
            quantity=raw["quantity"],
            filled_quantity=raw.get("filled_quantity", 0),
            average_price=raw.get("average_price") or None,
            limit_price=raw.get("price") or None,
            rejection_reason=raw.get("status_message") or None,
            raw=raw,
        )
