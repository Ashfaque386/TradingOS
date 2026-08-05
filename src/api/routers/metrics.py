"""Prometheus scrape endpoint (Phase 4 Epic E4.2), per Phase_8_DevOps_Architecture.md §5
("Metrics: Prometheus & Grafana")."""

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from src.data.reference.nse_holiday_calendar import is_trading_holiday
from src.observability.metrics import TRADING_HOLIDAY_TODAY

router = APIRouter(tags=["metrics"])

_IST = ZoneInfo("Asia/Kolkata")


@router.get("/metrics")
def metrics() -> Response:
    # REL-020 E20.1: refresh the holiday gauge on every scrape rather than on a background
    # timer -- cheap (one dict lookup), always reflects the current IST calendar date.
    today_ist = datetime.now(_IST).date()
    TRADING_HOLIDAY_TODAY.set(1 if is_trading_holiday(today_ist) else 0)
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
