"""REL-067: src.data.market_pulse's own change_pct math and multi-ticker orchestration, against
fixture data -- the real yfinance-network coverage lives in
tests/integration/test_market_data_skills.py (IndiaVixSkill/NseSectorDataSkill, unchanged return
shape after this module's extraction) and tests/integration/test_market_data_router.py
(GET /market/pulse)."""

import pandas as pd
import pytest

from src.data.market_pulse import SECTOR_TICKERS, _to_pulse, get_market_pulse


def _history(closes: list[float], dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"Close": closes}, index=pd.to_datetime(dates))


def test_to_pulse_computes_change_pct_against_previous_session():
    history = _history([100.0, 110.0], ["2026-08-13", "2026-08-14"])
    result = _to_pulse("Test Index", history)
    assert result is not None
    assert result.value == pytest.approx(110.0)
    assert result.change_pct == pytest.approx(10.0)
    assert result.as_of.isoformat() == "2026-08-14"


def test_to_pulse_change_pct_is_zero_with_only_one_session():
    result = _to_pulse("Test Index", _history([100.0], ["2026-08-14"]))
    assert result is not None
    assert result.change_pct == 0.0


def test_to_pulse_returns_none_for_empty_history():
    assert _to_pulse("Test Index", pd.DataFrame()) is None


def test_get_market_pulse_omits_a_sector_whose_fetch_raises(monkeypatch):
    def fake_vix() -> pd.DataFrame:
        return _history([20.0, 21.0], ["2026-08-13", "2026-08-14"])

    def fake_sector(ticker: str) -> pd.DataFrame:
        if ticker == SECTOR_TICKERS["IT"]:
            raise RuntimeError("real network failure for test")
        return _history([100.0, 105.0], ["2026-08-13", "2026-08-14"])

    monkeypatch.setattr("src.data.market_pulse.fetch_india_vix_history", fake_vix)
    monkeypatch.setattr("src.data.market_pulse.fetch_sector_history", fake_sector)

    pulse = get_market_pulse()

    assert pulse.india_vix is not None
    assert pulse.india_vix.value == pytest.approx(21.0)
    sector_names = {s.name for s in pulse.sectors}
    assert "IT" not in sector_names
    assert len(pulse.sectors) == len(SECTOR_TICKERS) - 1
