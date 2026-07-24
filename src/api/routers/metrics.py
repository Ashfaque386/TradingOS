"""Prometheus scrape endpoint (Phase 4 Epic E4.2), per Phase_8_DevOps_Architecture.md §5
("Metrics: Prometheus & Grafana")."""

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
