"""REL-009 E9.6 helper: publishes real synthetic ticks to the exact real Redis pub/sub channel
`stream_market_ticks` relays from (`src/memory/redis_client.py::TICK_CHANNEL_PREFIX`), so
`websocket_load.js`'s k6 run has something real to measure relay latency against.

This dev environment has no continuously-running live broker WebSocket feed, so without this,
a k6 run against /stream/market/{symbol} would measure connection overhead only (zero messages
ever relayed) -- not a fabricated data source, but a real gap this script closes honestly:
run it in parallel with the k6 script during a real perf run, not silently baked into the
measured numbers as if it were live market data.

Usage: docker compose exec app python tests/perf/publish_synthetic_ticks.py RELIANCE --rate 5
"""

import argparse
import json
import time
from datetime import UTC, datetime

import redis

from src.core.config import get_settings
from src.memory.redis_client import TICK_CHANNEL_PREFIX


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbol")
    parser.add_argument("--rate", type=float, default=5.0, help="ticks per second")
    parser.add_argument("--duration", type=float, default=60.0, help="seconds to run")
    args = parser.parse_args()

    client = redis.Redis.from_url(get_settings().redis_url)
    channel = f"{TICK_CHANNEL_PREFIX}{args.symbol}"
    interval = 1.0 / args.rate
    deadline = time.monotonic() + args.duration
    price = 2500.0
    sent = 0

    print(f"Publishing real synthetic ticks to {channel!r} at {args.rate}/s for {args.duration}s")
    while time.monotonic() < deadline:
        price += 0.5 if sent % 2 == 0 else -0.5
        payload = {
            "symbol": args.symbol,
            "price": round(price, 2),
            "volume": 100,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        client.publish(channel, json.dumps(payload))
        sent += 1
        time.sleep(interval)

    print(f"Done -- published {sent} real ticks.")


if __name__ == "__main__":
    main()
