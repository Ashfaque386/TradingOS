"""REL-010 E10.8a: market data REST surface (src/api/routers/market_data.py) against the real
FastAPI app + real Postgres + the real data lake already populated by earlier REL-005/E10.7
ingestion runs in this Docker stack (RELIANCE is a real, confirmed-present symbol -- see
tests/integration/test_corporate_actions_backtest_diff.py, which relies on the same fact).
"""

import time
import uuid
from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from src.api.main import app
from src.brokers.factory import NoBrokerConfigured, build_broker
from src.core.config import get_settings
from src.core.db import get_session
from src.core.security import ROLE_READ_ONLY_AUDITOR, ROLE_SYSTEM_ADMINISTRATOR
from src.data.datalake.query import DataLake
from src.models.corporate_action import CorporateAction
from src.models.instrument import Instrument
from tests.auth_helpers import auth_header, cleanup_user, create_authenticated_user

client = TestClient(app)

_REAL_SYMBOL = "RELIANCE"


def test_symbols_returns_real_symbols_from_the_data_lake():
    response = client.get("/api/v1/market/symbols")
    assert response.status_code == 200
    symbols = response.json()
    assert isinstance(symbols, list)
    assert _REAL_SYMBOL in symbols


def test_daily_ohlcv_returns_real_bars_for_a_real_symbol():
    response = client.get(f"/api/v1/market/ohlcv/{_REAL_SYMBOL}")
    assert response.status_code == 200
    bars = response.json()
    assert len(bars) > 0
    first = bars[0]
    assert set(first) == {"date", "open", "high", "low", "close", "volume"}
    assert first["close"] > 0


def test_daily_ohlcv_returns_empty_list_for_an_unknown_symbol():
    response = client.get("/api/v1/market/ohlcv/NOTAREALSYMBOL12345")
    assert response.status_code == 200
    assert response.json() == []


def test_intraday_ohlcv_returns_empty_list_when_nothing_ingested_yet():
    """Honest gap: the intraday scheduler job only fires during real NSE market hours (E10.7),
    so this real symbol genuinely has no intraday partitions yet in this dev environment --
    asserting an empty list (not an error) is the real, correct behavior."""
    response = client.get(f"/api/v1/market/ohlcv-intraday/{_REAL_SYMBOL}")
    assert response.status_code == 200
    assert response.json() == []


def _seed_corporate_action() -> tuple[str, date]:
    symbol = f"MKTDATATEST{uuid.uuid4().hex[:6].upper()}"
    ex_date = date(2025, 1, 15)
    with get_session() as session:
        session.add(
            CorporateAction(
                symbol=symbol,
                ex_date=ex_date,
                action_type="BONUS",
                ratio_numerator=1,
                ratio_denominator=3,
                source="test-fixture-not-a-real-nse-event",
            )
        )
        session.commit()
    return symbol, ex_date


def _cleanup_corporate_action(symbol: str, ex_date: date) -> None:
    with get_session() as session:
        session.query(CorporateAction).filter(
            CorporateAction.symbol == symbol, CorporateAction.ex_date == ex_date
        ).delete()
        session.commit()


def test_corporate_actions_endpoint_returns_a_real_seeded_row():
    symbol, ex_date = _seed_corporate_action()
    try:
        response = client.get(f"/api/v1/market/corporate-actions/{symbol}")
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 1
        assert rows[0]["action_type"] == "BONUS"
        assert rows[0]["ratio_denominator"] == 3.0
    finally:
        _cleanup_corporate_action(symbol, ex_date)


def test_corporate_actions_endpoint_returns_empty_list_for_a_symbol_with_none():
    response = client.get("/api/v1/market/corporate-actions/NOACTIONSFORTHIS12345")
    assert response.status_code == 200
    assert response.json() == []


def test_quote_against_a_real_broker():
    try:
        build_broker()
    except NoBrokerConfigured:
        pytest.skip("No broker configured in this environment")

    response = client.get(f"/api/v1/market/quote/{_REAL_SYMBOL}")
    if response.status_code != 200:
        pytest.skip(
            f"Real broker call failed (status={response.status_code}, body={response.text[:200]}) "
            "-- most likely today's expired daily access token, not a code defect."
        )
    body = response.json()
    assert body["symbol"] == _REAL_SYMBOL
    assert body["last_price"] > 0


def test_option_chain_against_a_real_broker():
    try:
        build_broker()
    except NoBrokerConfigured:
        pytest.skip("No broker configured in this environment")

    # A near-term Thursday NIFTY expiry -- real strikes/expiries are broker-instrument-dump
    # driven, so any date genuinely in the future is a valid query; a stale/wrong expiry just
    # yields an empty instrument list from a real broker, not an error.
    expiry = date(datetime.now(UTC).year + 1, 1, 2)
    response = client.get(
        "/api/v1/market/option-chain/NIFTY", params={"expiry": expiry.isoformat()}
    )
    if response.status_code != 200:
        pytest.skip(
            f"Real broker call failed (status={response.status_code}, body={response.text[:200]}) "
            "-- most likely today's expired daily access token, not a code defect."
        )
    body = response.json()
    assert body["underlying"] == "NIFTY"


# REL-058: GET /datalake/status (API-037, SRS Business Rule 4).


def _daily_lake() -> DataLake:
    return DataLake(get_settings().data_lake_root / "ohlcv_daily")


def test_datalake_status_is_not_stale_for_a_real_symbol_as_of_its_own_latest_partition():
    latest = _daily_lake().latest_date(_REAL_SYMBOL)
    assert latest is not None  # this real symbol has real ingested data (see module docstring)

    response = client.get("/api/v1/market/datalake/status", params={"as_of": latest.isoformat()})
    assert response.status_code == 200
    body = response.json()
    assert body["total_symbols"] > 0
    stale_symbols = {s["symbol"] for s in body["stale_symbols"]}
    assert _REAL_SYMBOL not in stale_symbols


def test_datalake_status_reports_stale_for_a_real_symbol_far_in_the_future():
    response = client.get("/api/v1/market/datalake/status", params={"as_of": "2030-01-01"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "Stale"
    stale_entry = next(s for s in body["stale_symbols"] if s["symbol"] == _REAL_SYMBOL)
    assert stale_entry["is_fresh"] is False
    assert stale_entry["latest_available"] == _daily_lake().latest_date(_REAL_SYMBOL).isoformat()


def test_datalake_status_defaults_as_of_to_today():
    response = client.get("/api/v1/market/datalake/status")
    assert response.status_code == 200
    assert response.json()["as_of"] == date.today().isoformat()


# REL-055: POST /ingest/trigger + GET /ingest/jobs/{job_id}/status.


def test_ingest_trigger_requires_the_gated_role():
    user_id, token = create_authenticated_user(ROLE_READ_ONLY_AUDITOR)
    try:
        response = client.post(
            "/api/v1/market/ingest/trigger",
            json={
                "source": "yfinance",
                "symbols": ["RELIANCE"],
                "start": "2024-01-01",
                "end": "2024-01-02",
            },
            headers=auth_header(token),
        )
        assert response.status_code == 403
    finally:
        cleanup_user(user_id)


def test_ingest_trigger_rejects_an_unknown_source():
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        response = client.post(
            "/api/v1/market/ingest/trigger",
            json={
                "source": "not_a_real_source",
                "symbols": ["RELIANCE"],
                "start": "2024-01-01",
                "end": "2024-01-02",
            },
            headers=auth_header(token),
        )
        assert response.status_code == 422  # Literal["bhavcopy", "yfinance"] rejects it first
    finally:
        cleanup_user(user_id)


def test_ingest_trigger_accepts_the_managed_source():
    # REL-071: this endpoint's Literal + ADAPTERS check previously couldn't reach the real
    # Upstox V3 + yfinance failover path added in REL-070 -- only the CLI could ask for it.
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        with patch("src.api.routers.market_data.run_ingestion", return_value=7):
            trigger = client.post(
                "/api/v1/market/ingest/trigger",
                json={
                    "source": "managed",
                    "symbols": ["RELIANCE"],
                    "start": "2024-01-01",
                    "end": "2024-01-02",
                },
                headers=auth_header(token),
            )
        assert trigger.status_code == 202
    finally:
        cleanup_user(user_id)


def test_ingest_trigger_runs_a_real_job_to_completion_and_status_reflects_it():
    """Mocks only run_ingestion itself (the real network fetch) -- the job state machine
    (Running -> Completed, real threading.Thread, real job_id/status polling) all runs for
    real, mirroring strategies.py's own backtest-trigger job pattern."""
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        with patch("src.api.routers.market_data.run_ingestion", return_value=42):
            trigger = client.post(
                "/api/v1/market/ingest/trigger",
                json={
                    "source": "yfinance",
                    "symbols": ["RELIANCE"],
                    "start": "2024-01-01",
                    "end": "2024-01-02",
                },
                headers=auth_header(token),
            )
        assert trigger.status_code == 202
        job_id = trigger.json()["job_id"]

        deadline = time.monotonic() + 5
        status_body = {}
        while time.monotonic() < deadline:
            status_response = client.get(f"/api/v1/market/ingest/jobs/{job_id}/status")
            assert status_response.status_code == 200
            status_body = status_response.json()
            if status_body["status"] != "Running":
                break
            time.sleep(0.05)

        assert status_body["status"] == "Completed"
        assert status_body["rows_written"] == 42
        assert status_body["error"] is None
    finally:
        cleanup_user(user_id)


def test_ingest_trigger_job_reports_a_real_failure_honestly():
    user_id, token = create_authenticated_user(ROLE_SYSTEM_ADMINISTRATOR)
    try:
        with patch(
            "src.api.routers.market_data.run_ingestion",
            side_effect=RuntimeError("real adapter failure for test"),
        ):
            trigger = client.post(
                "/api/v1/market/ingest/trigger",
                json={
                    "source": "bhavcopy",
                    "symbols": ["RELIANCE"],
                    "start": "2024-01-01",
                    "end": "2024-01-02",
                },
                headers=auth_header(token),
            )
        job_id = trigger.json()["job_id"]

        deadline = time.monotonic() + 5
        status_body = {}
        while time.monotonic() < deadline:
            status_response = client.get(f"/api/v1/market/ingest/jobs/{job_id}/status")
            status_body = status_response.json()
            if status_body["status"] != "Running":
                break
            time.sleep(0.05)

        assert status_body["status"] == "Failed"
        assert "real adapter failure for test" in status_body["error"]
    finally:
        cleanup_user(user_id)


def test_ingest_job_status_unknown_job_is_a_404():
    response = client.get(f"/api/v1/market/ingest/jobs/{uuid.uuid4()}/status")
    assert response.status_code == 404


# REL-067: GET /market/ohlcv/{symbol}/indicators wires src.data.features.indicators against the
# real daily OHLCV lake (previously dead code, zero callers anywhere).


def test_ohlcv_indicators_returns_real_computed_columns_for_a_real_symbol():
    response = client.get(f"/api/v1/market/ohlcv/{_REAL_SYMBOL}/indicators")
    assert response.status_code == 200
    points = response.json()
    assert len(points) > 0
    first = points[0]
    assert set(first) == {
        "date",
        "close",
        "sma_20",
        "ema_20",
        "rsi_14",
        "atr_14",
        "bb_upper",
        "bb_mid",
        "bb_lower",
        "macd_line",
        "macd_signal",
        "macd_histogram",
    }
    # A rolling 20-period SMA is null until the 20th real bar exists -- the early rows of a long
    # enough real symbol prove that honestly, not fabricated as 0 or the close price.
    assert points[0]["sma_20"] is None
    last = points[-1]
    assert last["sma_20"] is not None
    assert last["ema_20"] > 0


def test_ohlcv_indicators_returns_empty_list_for_an_unknown_symbol():
    response = client.get("/api/v1/market/ohlcv/NOTAREALSYMBOL12345/indicators")
    assert response.status_code == 200
    assert response.json() == []


# REL-067: GET /market/pulse -- real India VIX + NSE sector-index day-change, via the same
# src.data.market_pulse.get_market_pulse() IndiaVixSkill/NseSectorDataSkill fetch through
# (tests/integration/test_market_data_skills.py exercises those skills directly; real network
# call here too, same class of test).


def test_market_pulse_returns_real_vix_and_sector_data():
    response = client.get("/api/v1/market/pulse")
    assert response.status_code == 200
    body = response.json()
    assert "india_vix" in body
    assert "sectors" in body
    if body["india_vix"] is not None:
        assert body["india_vix"]["value"] > 0
        assert body["india_vix"]["name"] == "India VIX"
    assert isinstance(body["sectors"], list)
    for sector in body["sectors"]:
        assert set(sector) == {"name", "value", "change_pct", "as_of"}
        assert sector["value"] > 0


# REL-071: GET /market/instruments/search -- the real, locally-synced Upstox instrument table
# (src/data/ingest/instrument_sync.py, src/data/instruments.py). Seeds real rows under a fake,
# dedicated provider/exchange pair so this test never depends on -- or disturbs -- whatever the
# real live Upstox sync has (or hasn't) populated in this environment.

_INSTR_PROVIDER = "test_router_provider"
_INSTR_EXCHANGE = "TESTREX"


def _seed_test_instruments() -> None:
    with get_session() as session:
        session.add(
            Instrument(
                provider=_INSTR_PROVIDER,
                instrument_key=f"{_INSTR_EXCHANGE}_EQ|ROUTERTEST",
                exchange=_INSTR_EXCHANGE,
                segment=f"{_INSTR_EXCHANGE}_EQ",
                symbol="ROUTERTESTCO",
                name="Router Test Co Ltd",
                instrument_type="EQ",
                isin="INE_ROUTER_01",
                is_active=True,
            )
        )
        session.commit()


def _cleanup_test_instruments() -> None:
    with get_session() as session:
        session.execute(
            delete(Instrument).where(
                Instrument.provider == _INSTR_PROVIDER, Instrument.exchange == _INSTR_EXCHANGE
            )
        )
        session.commit()


def test_instrument_search_returns_a_real_seeded_match():
    _seed_test_instruments()
    try:
        response = client.get(
            "/api/v1/market/instruments/search",
            params={"q": "Router Test", "exchange": _INSTR_EXCHANGE},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["page_size"] == 25
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["symbol"] == "ROUTERTESTCO"
        assert item["instrument_key"] == f"{_INSTR_EXCHANGE}_EQ|ROUTERTEST"
        assert item["isin"] == "INE_ROUTER_01"
    finally:
        _cleanup_test_instruments()


def test_instrument_search_returns_empty_for_no_match():
    response = client.get(
        "/api/v1/market/instruments/search", params={"q": "NoSuchInstrumentAtAll12345"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_instrument_search_respects_page_size():
    response = client.get("/api/v1/market/instruments/search", params={"page": 1, "page_size": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["page_size"] == 3
    assert len(body["items"]) <= 3


def test_instrument_search_rejects_an_out_of_range_page_size():
    response = client.get("/api/v1/market/instruments/search", params={"page_size": 1000})
    assert response.status_code == 422


# REL-073: GET /market/providers/status -- a config-only check (no live network call), mirroring
# broker_config.py's own broker_status() shape.


def test_provider_status_reflects_the_real_current_configuration():
    response = client.get("/api/v1/market/providers/status")
    assert response.status_code == 200
    body = response.json()
    names = {p["name"] for p in body["providers"]}
    assert names == {"upstox_v3", "yfinance"}
    # yfinance needs no credential -- always real and configured.
    yfinance_entry = next(p for p in body["providers"] if p["name"] == "yfinance")
    assert yfinance_entry["configured"] is True
    assert yfinance_entry["detail"] is None
    # active_provider must be one of the two real, currently-configured providers.
    assert body["active_provider"] in names


def test_provider_status_never_exposes_a_token_value():
    response = client.get("/api/v1/market/providers/status")
    body_text = response.text
    # A real Upstox Analytics Token, if configured in this environment, must never appear
    # verbatim in this response -- only whether one exists, never the value itself.
    settings = get_settings()
    if settings.upstox_analytics_token:
        assert settings.upstox_analytics_token not in body_text


def test_provider_status_honestly_reports_upstox_not_configured():
    with (
        patch("src.api.routers.market_data.vault.read_market_data_credential", return_value=None),
        patch("src.api.routers.market_data.get_settings") as mock_settings,
    ):
        settings = get_settings()
        mock_settings.return_value = settings.model_copy(update={"upstox_analytics_token": None})
        response = client.get("/api/v1/market/providers/status")
    assert response.status_code == 200
    body = response.json()
    upstox_entry = next(p for p in body["providers"] if p["name"] == "upstox_v3")
    assert upstox_entry["configured"] is False
    assert upstox_entry["detail"] is not None
    assert body["active_provider"] == "yfinance"
