"""REL-010 E10.3 / T100: fetch_india_vix/fetch_nse_sector_data/fetch_global_indices all hit the
real Yahoo Finance API (confirmed working tickers) -- real network calls, hence integration not
unit."""

from src.agents.tools.skills import GlobalIndicesSkill, IndiaVixSkill, NseSectorDataSkill


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


def test_fetch_global_indices_returns_real_closes_for_at_least_one_index():
    """T100/BUG-D: degrades per-ticker on failure (never fabricates a missing one), so this only
    asserts at least one of the 5 real tickers came back -- a hard "all 5" assertion would make
    this test flaky against any single real yfinance/network hiccup."""
    result = GlobalIndicesSkill().execute()
    assert result
    for entry in result.values():
        assert "close" in entry
        assert isinstance(entry["close"], float)
