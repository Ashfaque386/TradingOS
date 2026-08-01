"""REL-015 E15.6 (GLH-12): standing continuous tick publisher.

Closes the real gap REL-011 E11.1's own exit criteria already named honestly: "no live/
simulated tick publisher runs continuously in this dev environment ... continuous live updates
are code-verified but not demonstrated as an ongoing stream" -- the same gap the portfolio
ticker (`GET /stream/portfolio`) shares. This worker polls each real symbol in the data lake for
its real current quote (`broker.get_quote()`, the same call the Paper Trading Engine's
depth-walk already uses) every `POLL_INTERVAL_SECONDS` during real NSE market hours, and
publishes to the same Redis channel `stream_market_ticks` (`src/api/routers/streams.py`) already
relays from -- consumers (the frontend's candlestick chart, `useMarketStream`) see a continuous
stream with zero changes on their own side.

Real REST polling, not a real broker WebSocket tick feed: Zerodha's KiteTicker / Upstox's own WS
feed would need persistent connection management, reconnect/backoff logic, and per-symbol
subscription handling -- a genuinely larger integration than this epic scoped for. A ~5s REST
poll per symbol is still a real, live, continuously-updating price feed (never simulated/
fabricated data), just a coarser cadence than a true tick-by-tick WS stream -- documented here as
the honest scope, not silently presented as the same thing.

Rebuilds the broker adapter every cycle rather than caching one: matches this codebase's
existing per-call `build_broker()` pattern elsewhere (routers construct one per request, not a
process-wide singleton) and correctly picks up a freshly-rotated access token (e.g. from
`scripts/daily_broker_login_helper.py`) on the very next cycle rather than holding a stale one.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from src.brokers.factory import NoBrokerConfigured, build_broker
from src.core.config import get_settings
from src.data.datalake.query import DataLake
from src.data.reference.nse_holiday_calendar import is_trading_holiday
from src.engine.live.tick_listener import get_async_redis_client
from src.memory.redis_client import TICK_CHANNEL_PREFIX

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tick_publisher")

IST = ZoneInfo("Asia/Kolkata")
POLL_INTERVAL_SECONDS = 5

# NSE/BSE real cash-market session, matching the same 09:15-15:30 IST window
# src/agents/scheduler.py's news/sentiment cron job already targets.
_MARKET_OPEN_MINUTES = 9 * 60 + 15
_MARKET_CLOSE_MINUTES = 15 * 60 + 30


def _is_market_open(now_ist: datetime) -> bool:
    if now_ist.weekday() >= 5:  # Monday=0 .. Saturday=5, Sunday=6
        return False
    if is_trading_holiday(now_ist.date()):
        return False
    now_minutes = now_ist.hour * 60 + now_ist.minute
    return _MARKET_OPEN_MINUTES <= now_minutes <= _MARKET_CLOSE_MINUTES


async def _publish_once(symbols: list[str]) -> None:
    try:
        broker = build_broker()
    except NoBrokerConfigured:
        logger.warning("No broker configured -- cannot publish real ticks this cycle.")
        return

    redis_client = get_async_redis_client()
    try:
        for symbol in symbols:
            try:
                quote = await broker.get_quote(symbol)
            except Exception as exc:  # noqa: BLE001 -- one symbol's failure must not stop the rest
                logger.warning("get_quote(%s) failed (will retry next cycle): %s", symbol, exc)
                continue
            payload = json.dumps(
                {
                    "price": quote.last_price,
                    "volume": 0,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            await redis_client.publish(f"{TICK_CHANNEL_PREFIX}{symbol}", payload)
            logger.info("Published real tick: %s @ %s", symbol, quote.last_price)
    finally:
        await redis_client.aclose()


async def main() -> None:
    settings = get_settings()
    data_lake = DataLake(settings.data_lake_root)
    logger.info(
        "Tick publisher starting (REL-015 E15.6) -- polling every %ss during real NSE market "
        "hours.",
        POLL_INTERVAL_SECONDS,
    )
    while True:
        try:
            now_ist = datetime.now(IST)
            if _is_market_open(now_ist):
                symbols = data_lake.list_symbols()
                if symbols:
                    await _publish_once(symbols)
                else:
                    logger.warning("No symbols found in the data lake -- nothing to publish.")
        except Exception as exc:  # noqa: BLE001 -- must never crash this standing loop
            logger.warning("Tick publisher cycle failed (will retry): %s", exc)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
