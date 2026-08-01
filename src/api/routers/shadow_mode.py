"""Shadow Mode endpoints (Phase 4 Epic E4.4), backing the go-live gate in
Phase_9_Master_Implementation_Guide.md §4/§6: "Shadow Mode has run for 5 consecutive days with
zero broker API syntax errors." See src/brokers/shadow_mode.py's module docstring for why
Zerodha and Upstox attempts are handled honestly differently (no broker-agnostic "dry run" flag
actually exists on either broker's real API).

UPDATE 2026-08-01 (SEC-046, found during a paper-trading-dashboard research pass): POST /attempt
had NO auth dependency at all -- any unauthenticated caller could trigger a real order-placement
call against Upstox's real sandbox (used_real_sandbox=True path), not just a harmless local
payload build. Gated to the same SystemAdministrator/PortfolioManager/RiskManager set as
POST /paper-trading/execute and POST /strategies/{id}/backtest (same precedent as REL-011
E10.11.0/SEC-045). GET /status stays open (Any role, matching this codebase's existing
read-endpoint convention) -- only the mutating, broker-calling endpoint was ever the gap.
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from src.api.deps import require_role
from src.brokers.base import BrokerAdapter, OrderRequest, OrderType, ProductType, Side, Validity
from src.brokers.factory import NoBrokerConfigured, build_upstox_adapter, build_zerodha_adapter
from src.brokers.shadow_mode import ShadowModeAdapter
from src.core.db import get_session
from src.core.security import ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER, ROLE_SYSTEM_ADMINISTRATOR
from src.engine.shadow_mode_status import compute_daily_summary, consecutive_clean_days
from src.models.shadow_mode import ShadowModeAttempt
from src.models.user import User

router = APIRouter(prefix="/api/v1/shadow-mode", tags=["shadow-mode"])

BrokerName = Literal["zerodha", "upstox"]

_can_attempt_shadow_order = require_role(
    ROLE_SYSTEM_ADMINISTRATOR, ROLE_PORTFOLIO_MANAGER, ROLE_RISK_MANAGER, audit_denials=True
)


class AttemptRequest(BaseModel):
    broker: BrokerName
    symbol: str
    side: Side
    order_type: OrderType = "MARKET"
    quantity: int
    product: ProductType = "INTRADAY"
    limit_price: float | None = None
    trigger_price: float | None = None
    validity: Validity = "DAY"


class AttemptResponse(BaseModel):
    id: uuid.UUID
    broker: str
    outcome: str
    error_detail: str | None
    latency_ms: float
    used_real_sandbox: bool
    attempted_at: datetime


def _build_adapter(broker: BrokerName) -> BrokerAdapter:
    if broker == "zerodha":
        return build_zerodha_adapter()
    return build_upstox_adapter()


@router.post("/attempt", response_model=AttemptResponse, status_code=201)
async def attempt(
    body: AttemptRequest, _user: User = Depends(_can_attempt_shadow_order)
) -> AttemptResponse:
    try:
        broker_adapter = _build_adapter(body.broker)
    except NoBrokerConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    order = OrderRequest(
        symbol=body.symbol,
        side=body.side,
        order_type=body.order_type,
        quantity=body.quantity,
        product=body.product,
        limit_price=body.limit_price,
        trigger_price=body.trigger_price,
        validity=body.validity,
    )
    shadow = ShadowModeAdapter(broker_adapter, broker_name=body.broker)
    result = await shadow.attempt_order(order)

    attempted_at = datetime.now(UTC)
    with get_session() as session:
        row = ShadowModeAttempt(
            broker=result.broker,
            symbol=body.symbol,
            side=body.side,
            request_payload=result.request_payload,
            outcome=result.outcome,
            error_detail=result.error_detail,
            latency_ms=result.latency_ms,
            used_real_sandbox=result.used_real_sandbox,
            attempted_at=attempted_at,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return AttemptResponse(
            id=row.id,
            broker=row.broker,
            outcome=row.outcome,
            error_detail=row.error_detail,
            latency_ms=float(row.latency_ms),
            used_real_sandbox=row.used_real_sandbox,
            attempted_at=row.attempted_at,
        )


class DailySummary(BaseModel):
    date: str
    attempts: int
    errors: int
    clean: bool  # at least one attempt, zero errors


class ShadowModeStatus(BaseModel):
    consecutive_clean_days: int
    go_live_gate_met: bool  # per Phase_9 §4/§6: 5 consecutive clean days
    daily_summary: list[DailySummary]


@router.get("/status", response_model=ShadowModeStatus)
def status() -> ShadowModeStatus:
    """Computed fresh from the real ledger every call -- 'consecutive clean days' is only ever
    as real as however many days this has actually been run for. A brand-new deployment
    honestly reports 0, not a fabricated number working toward 5."""
    with get_session() as session:
        stmt = select(ShadowModeAttempt).order_by(ShadowModeAttempt.attempted_at)
        rows = list(session.scalars(stmt))

    daily = compute_daily_summary(rows)
    consecutive = consecutive_clean_days(daily)

    return ShadowModeStatus(
        consecutive_clean_days=consecutive,
        go_live_gate_met=consecutive >= 5,
        daily_summary=[
            DailySummary(date=d.date, attempts=d.attempts, errors=d.errors, clean=d.clean)
            for d in daily
        ],
    )
