"""UpstoxV3Provider integration test against the REAL, LIVE Upstox V3 Historical Candle Data API
(REL-070, Phase 1 exit criterion -- spec's own Test 1: "Request RELIANCE 2018-01-01 -> 2026-08-15
1d. The application retrieves valid historical data using Upstox V3.").

SAFETY: the Analytics Token is inherently read-only (no order-placement capability) and this
provider always targets the real production host (see src/data/providers/upstox_v3.py's own
module docstring for why there's no sandbox toggle) -- real market data, zero funds-risk.

Skipped entirely unless UPSTOX_ANALYTICS_TOKEN is configured -- same "real credential or honest
skip" convention as tests/integration/test_kite_connect_live.py.
"""

from datetime import date, timedelta

import pytest

from src.core.config import get_settings
from src.data.providers.upstox_v3 import UpstoxV3Provider

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not settings.upstox_analytics_token,
    reason="UPSTOX_ANALYTICS_TOKEN not configured -- see .env.example for how to generate one "
    "(Developer Apps -> Analytics tab -> Generate Token)",
)

# NSE_EQ|INE002A01018 is Reliance Industries' real, confirmed Upstox instrument_key.
_RELIANCE_INSTRUMENT_KEY = "NSE_EQ|INE002A01018"


def test_get_historical_data_against_the_real_reliance_instrument():
    end = date.today()
    start = end - timedelta(days=14)

    with UpstoxV3Provider(token=settings.upstox_analytics_token) as provider:
        candles = provider.get_historical_data(
            instrument_key=_RELIANCE_INSTRUMENT_KEY,
            symbol="RELIANCE",
            start=start,
            end=end,
            timeframe="1d",
        )

    assert len(candles) > 0
    for candle in candles:
        assert candle.high >= candle.low
        assert candle.close > 0
        assert candle.provider == "upstox_v3"


def test_health_check_against_the_real_api():
    with UpstoxV3Provider(token=settings.upstox_analytics_token) as provider:
        assert provider.health_check() is True
