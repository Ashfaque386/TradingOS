"""`src/workers/tick_publisher.py::_publish_once` unit coverage -- the module had no dedicated
test until now (its own docstring notes it had "never actually been exercised" for real, since
`_is_market_open()` gates the whole loop and the worker had only ever run outside market hours).

`build_broker` and the async Redis client are patched -- this is about the publisher's own
per-symbol iteration/skip/publish behaviour, not a real broker or a real Redis.
"""

from unittest.mock import AsyncMock, patch

import pytest

from src.brokers.base import Quote
from src.memory.redis_client import TICK_CHANNEL_PREFIX
from src.workers.tick_publisher import _publish_once


def _chan(symbol: str) -> str:
    return f"{TICK_CHANNEL_PREFIX}{symbol}"


def _quote(symbol: str, last_price: float) -> Quote:
    return Quote(symbol=symbol, last_price=last_price)


@pytest.mark.asyncio
async def test_publish_once_publishes_a_real_tick_per_resolvable_symbol():
    broker = AsyncMock()
    broker.get_quote.side_effect = lambda s: _quote(s, {"RELIANCE": 1289.0, "TCS": 2262.0}[s])
    redis_client = AsyncMock()

    with (
        patch("src.workers.tick_publisher.build_broker", return_value=broker),
        patch("src.workers.tick_publisher.get_async_redis_client", return_value=redis_client),
    ):
        await _publish_once(["RELIANCE", "TCS"])

    published = {call.args[0]: call.args[1] for call in redis_client.publish.call_args_list}
    assert set(published) == {_chan("RELIANCE"), _chan("TCS")}
    assert '"price": 1289.0' in published[_chan("RELIANCE")]


@pytest.mark.asyncio
async def test_publish_once_skips_caret_prefixed_index_tickers_without_calling_the_broker():
    """`^NSEI` (Nifty 50, a yfinance ticker convention) has no real broker live-quote path --
    Kite 403s on `NSE:^NSEI` and Upstox's instrument search matches an unrelated equity, so a
    published "tick" would be a fabricated price. It must be skipped, and the broker must not be
    asked for it at all."""
    broker = AsyncMock()
    broker.get_quote.side_effect = lambda s: _quote(s, 1289.0)
    redis_client = AsyncMock()

    with (
        patch("src.workers.tick_publisher.build_broker", return_value=broker),
        patch("src.workers.tick_publisher.get_async_redis_client", return_value=redis_client),
    ):
        await _publish_once(["^NSEI", "RELIANCE"])

    broker.get_quote.assert_awaited_once_with("RELIANCE")
    published_channels = [call.args[0] for call in redis_client.publish.call_args_list]
    assert published_channels == [_chan("RELIANCE")]


@pytest.mark.asyncio
async def test_publish_once_continues_past_one_symbols_quote_failure():
    broker = AsyncMock()

    async def _get_quote(symbol: str) -> Quote:
        if symbol == "BADSYM":
            raise RuntimeError("real per-symbol failure")
        return _quote(symbol, 100.0)

    broker.get_quote.side_effect = _get_quote
    redis_client = AsyncMock()

    with (
        patch("src.workers.tick_publisher.build_broker", return_value=broker),
        patch("src.workers.tick_publisher.get_async_redis_client", return_value=redis_client),
    ):
        await _publish_once(["BADSYM", "RELIANCE"])

    published_channels = [call.args[0] for call in redis_client.publish.call_args_list]
    assert published_channels == [_chan("RELIANCE")]
