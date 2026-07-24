"""Tick payload parsing tests (Phase 4 Epic E4.2)."""

import json
from datetime import UTC, datetime

from src.engine.live.tick_listener import parse_tick_payload


def test_parse_tick_payload_reads_price_and_timestamp():
    raw = json.dumps({"price": 2500.5, "timestamp": "2026-01-15T10:30:00+00:00"})

    tick = parse_tick_payload("RELIANCE", raw)

    assert tick.symbol == "RELIANCE"
    assert tick.price == 2500.5
    assert tick.timestamp == datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC)


def test_parse_tick_payload_defaults_timestamp_to_now_when_missing():
    raw = json.dumps({"price": 100.0})
    before = datetime.now(UTC)

    tick = parse_tick_payload("TCS", raw)

    after = datetime.now(UTC)
    assert before <= tick.timestamp <= after


def test_parse_tick_payload_coerces_integer_price_to_float():
    raw = json.dumps({"price": 100})

    tick = parse_tick_payload("TCS", raw)

    assert tick.price == 100.0
    assert isinstance(tick.price, float)
