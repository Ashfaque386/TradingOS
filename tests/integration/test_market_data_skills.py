"""REL-010 E10.3: fetch_india_vix/fetch_nse_sector_data now hit the real Yahoo Finance API
(confirmed working tickers) -- real network calls, hence integration not unit."""

from src.agents.tools.skills import IndiaVixSkill, NseSectorDataSkill


def test_fetch_india_vix_returns_a_real_close_price():
    result = IndiaVixSkill().execute()
    assert "close" in result
    assert isinstance(result["close"], float)
    assert result["close"] > 0


def test_fetch_nse_sector_data_returns_real_closes_for_known_sectors():
    result = NseSectorDataSkill().execute()
    assert "IT" in result
    assert "BANK" in result
    assert any("close" in v for v in result.values())
