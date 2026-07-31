"""Portfolio & Risk endpoints (Phase 4 Epic E4.3), per Phase_10_API_Design.md §9:

  API-057 GET /positions -- live open positions across brokers.
  API-059 GET /portfolio/margin -- aggregated margin.
  API-060 GET /portfolio/pnl -- realized/unrealized PnL against the daily stop-loss limit.

Plus a risk-metrics and allocation endpoint feeding the Portfolio & Risk Command Center
(Phase_7_Frontend_Architecture.md §2.2) gauges and exposure donuts.

Data sources are deliberately honest about what is and isn't real yet:
  - Positions/margin/PnL come straight from the live broker adapter (build_broker()) -- real
    account state, same pattern as system.py/streams.py.
  - Sharpe ratio is the capital-weighted average of each currently-"Live" strategy's most
    recent BacktestResult.sharpe_ratio (DB-007) -- a real, stored number, but it is a
    *backtested* Sharpe, not a live-trading one (no live equity-curve tracker exists yet).
    Returned with `sharpe_ratio_source` so the frontend can label it honestly.
  - Beta vs Nifty 50 needs a live equity curve correlated against index returns, which nothing
    in the codebase computes yet -- returned as `null` rather than fabricated.
  - Sector exposure has the same gap (no NSE sector-constituent mapping ingested -- see
    NseSectorDataSkill in src/agents/tools/skills.py, which is itself an honest stub for the
    same reason). `/portfolio/allocation` returns by-symbol exposure (real) plus explicit
    `sector_data_available` / `strategy_data_available` flags instead of inventing a mapping.

The read-only endpoints above predate real JWT/RBAC (REL-007) and stay ungated, matching every
other plain market-data-style read in this codebase (e.g. agents.py's `/runs`). REL-010 E10.5
adds the allocation-recommendation endpoints below, which ARE real RBAC-gated (mutating actions
need it; the reads next to them stay open for consistency with the rest of this file).
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents.nodes.portfolio_manager_agent import generate_allocation_recommendation
from src.api.deps import require_role
from src.brokers.base import BrokerAdapter, Margin, Position
from src.brokers.factory import NoBrokerConfigured, build_broker
from src.core.audit import write_audit_entry
from src.core.db import get_session
from src.core.security import ROLE_PORTFOLIO_MANAGER, ROLE_SYSTEM_ADMINISTRATOR
from src.models.portfolio_allocation_recommendation import PortfolioAllocationRecommendation
from src.models.strategy import BacktestResult, Strategy
from src.models.trading import RiskLimit
from src.models.user import User

router = APIRouter(prefix="/api/v1", tags=["portfolio"])

_can_manage_allocation = require_role(
    ROLE_SYSTEM_ADMINISTRATOR, ROLE_PORTFOLIO_MANAGER, audit_denials=True
)


class PnLResponse(BaseModel):
    unrealized_pnl: float
    realized_pnl: float
    total_pnl: float
    daily_loss_limit: float | None
    pct_of_daily_limit_used: float | None


class RiskMetricsResponse(BaseModel):
    sharpe_ratio: float | None
    sharpe_ratio_source: str
    beta_vs_nifty50: float | None
    daily_pnl: float
    daily_loss_limit: float | None
    pct_of_daily_limit_used: float | None
    max_sector_exposure_pct: float | None


class SymbolExposure(BaseModel):
    symbol: str
    market_value: float
    pct_of_gross: float


class AllocationResponse(BaseModel):
    by_symbol: list[SymbolExposure]
    gross_exposure: float
    sector_data_available: bool
    strategy_data_available: bool


def _get_broker() -> BrokerAdapter:
    try:
        return build_broker()
    except NoBrokerConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _latest_risk_limit(session: Session) -> RiskLimit | None:
    return session.scalars(
        select(RiskLimit)
        .where(RiskLimit.scope_type == "Global")
        .order_by(RiskLimit.effective_from.desc())
    ).first()


def _pct_of_daily_limit(total_pnl: float, daily_limit: float | None) -> float | None:
    if daily_limit and daily_limit > 0 and total_pnl < 0:
        return min(abs(total_pnl) / daily_limit * 100, 999.0)
    return None


@router.get("/positions", response_model=list[Position])
async def list_positions() -> list[Position]:
    """API-057."""
    broker = _get_broker()
    return await broker.get_positions()


@router.get("/portfolio/margin", response_model=Margin)
async def portfolio_margin() -> Margin:
    """API-059."""
    broker = _get_broker()
    return await broker.get_margin()


@router.get("/portfolio/pnl", response_model=PnLResponse)
async def portfolio_pnl() -> PnLResponse:
    """API-060 (realized/unrealized totals; per-trade STT/GST breakdown lives on Trade rows,
    DB-009, not summarized here)."""
    broker = _get_broker()
    positions = await broker.get_positions()
    unrealized = sum(p.unrealized_pnl for p in positions)
    realized = sum(p.realized_pnl for p in positions)
    total = unrealized + realized

    with get_session() as session:
        limit = _latest_risk_limit(session)
        daily_limit = float(limit.max_daily_loss) if limit else None

    return PnLResponse(
        unrealized_pnl=unrealized,
        realized_pnl=realized,
        total_pnl=total,
        daily_loss_limit=daily_limit,
        pct_of_daily_limit_used=_pct_of_daily_limit(total, daily_limit),
    )


@router.get("/portfolio/risk-metrics", response_model=RiskMetricsResponse)
async def portfolio_risk_metrics() -> RiskMetricsResponse:
    broker = _get_broker()
    positions = await broker.get_positions()
    daily_pnl = sum(p.unrealized_pnl + p.realized_pnl for p in positions)

    with get_session() as session:
        limit = _latest_risk_limit(session)
        daily_limit = float(limit.max_daily_loss) if limit else None
        max_sector_pct = (
            float(limit.max_sector_exposure_pct)
            if limit and limit.max_sector_exposure_pct is not None
            else None
        )

        live_strategies = list(session.scalars(select(Strategy).where(Strategy.status == "Live")))
        weighted_sum = 0.0
        weight_total = 0.0
        for strat in live_strategies:
            if not strat.current_version_id:
                continue
            result = session.scalars(
                select(BacktestResult)
                .where(BacktestResult.strategy_version_id == strat.current_version_id)
                .order_by(BacktestResult.created_at.desc())
            ).first()
            if result and result.sharpe_ratio is not None:
                weighted_sum += float(result.sharpe_ratio) * float(result.initial_capital)
                weight_total += float(result.initial_capital)
        sharpe = weighted_sum / weight_total if weight_total > 0 else None

    return RiskMetricsResponse(
        sharpe_ratio=sharpe,
        sharpe_ratio_source="backtest" if sharpe is not None else "unavailable",
        beta_vs_nifty50=None,
        daily_pnl=daily_pnl,
        daily_loss_limit=daily_limit,
        pct_of_daily_limit_used=_pct_of_daily_limit(daily_pnl, daily_limit),
        max_sector_exposure_pct=max_sector_pct,
    )


@router.get("/portfolio/allocation", response_model=AllocationResponse)
async def portfolio_allocation() -> AllocationResponse:
    broker = _get_broker()
    positions = await broker.get_positions()
    valued = [
        (p.symbol, abs(p.net_quantity) * (p.last_price or p.average_price or 0.0))
        for p in positions
        if p.net_quantity != 0
    ]
    gross = sum(v for _, v in valued)
    by_symbol = sorted(
        (
            SymbolExposure(
                symbol=sym, market_value=val, pct_of_gross=(val / gross * 100) if gross else 0.0
            )
            for sym, val in valued
        ),
        key=lambda s: s.market_value,
        reverse=True,
    )
    return AllocationResponse(
        by_symbol=by_symbol,
        gross_exposure=gross,
        sector_data_available=False,
        strategy_data_available=False,
    )


class AllocationRecommendationResponse(BaseModel):
    id: uuid.UUID
    generated_at: datetime
    recommendations: dict[str, object]
    rationale: str | None
    status: str
    decided_by_user_id: uuid.UUID | None
    decided_at: datetime | None


def _to_recommendation_response(
    row: PortfolioAllocationRecommendation,
) -> AllocationRecommendationResponse:
    return AllocationRecommendationResponse(
        id=row.id,
        generated_at=row.generated_at,
        recommendations=row.recommendations,
        rationale=row.rationale,
        status=row.status,
        decided_by_user_id=row.decided_by_user_id,
        decided_at=row.decided_at,
    )


@router.post(
    "/portfolio/allocation-recommendation/trigger",
    response_model=AllocationRecommendationResponse,
)
async def trigger_allocation_recommendation(
    _user: User = Depends(_can_manage_allocation),
) -> AllocationRecommendationResponse:
    """REL-010 E10.5 (AGT-016). Runs the Portfolio Manager Agent on demand against real
    current strategy/backtest data and the real broker margin -- advisory only, never applied
    to any real position."""
    broker = _get_broker()
    with get_session() as session:
        recommendation = await generate_allocation_recommendation(session, broker)
        if recommendation is None:
            raise HTTPException(
                status_code=422,
                detail="No eligible Live/PaperTrading strategy with a backtest result, or the "
                "LLM failed to produce a valid recommendation -- see server logs.",
            )
        return _to_recommendation_response(recommendation)


@router.get(
    "/portfolio/allocation-recommendation/latest",
    response_model=AllocationRecommendationResponse | None,
)
def latest_allocation_recommendation() -> AllocationRecommendationResponse | None:
    with get_session() as session:
        row = session.scalars(
            select(PortfolioAllocationRecommendation).order_by(
                PortfolioAllocationRecommendation.generated_at.desc()
            )
        ).first()
        return _to_recommendation_response(row) if row is not None else None


def _decide_recommendation(
    recommendation_id: uuid.UUID, *, new_status: str, user: User, action: str
) -> AllocationRecommendationResponse:
    with get_session() as session:
        row = session.get(PortfolioAllocationRecommendation, recommendation_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        if row.status != "Proposed":
            raise HTTPException(status_code=400, detail=f"Recommendation is already {row.status}")

        row.status = new_status
        row.decided_by_user_id = user.id
        row.decided_at = datetime.now(UTC)

        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=user.email,
            action=action,
            entity_type="PortfolioAllocationRecommendation",
            entity_id=row.id,
            after_state={"status": new_status},
        )
        session.commit()
        return _to_recommendation_response(row)


@router.post(
    "/portfolio/allocation-recommendation/{recommendation_id}/accept",
    response_model=AllocationRecommendationResponse,
)
def accept_allocation_recommendation(
    recommendation_id: uuid.UUID, user: User = Depends(_can_manage_allocation)
) -> AllocationRecommendationResponse:
    """Records real human sign-off only -- no automated position-sizing execution path exists
    anywhere in this codebase (Business Rule 3), so "Accepted" is a durable, audited record of
    the decision, not a trigger for anything else."""
    return _decide_recommendation(
        recommendation_id,
        new_status="Accepted",
        user=user,
        action="PORTFOLIO_ALLOCATION_RECOMMENDATION_ACCEPTED",
    )


@router.post(
    "/portfolio/allocation-recommendation/{recommendation_id}/reject",
    response_model=AllocationRecommendationResponse,
)
def reject_allocation_recommendation(
    recommendation_id: uuid.UUID, user: User = Depends(_can_manage_allocation)
) -> AllocationRecommendationResponse:
    return _decide_recommendation(
        recommendation_id,
        new_status="Rejected",
        user=user,
        action="PORTFOLIO_ALLOCATION_RECOMMENDATION_REJECTED",
    )
