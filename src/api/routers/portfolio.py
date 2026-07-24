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

Auth/RBAC gap matches every other Phase 4 router: no JWT/auth module exists yet.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.brokers.base import BrokerAdapter, Margin, Position
from src.brokers.factory import NoBrokerConfigured, build_broker
from src.core.db import get_session
from src.models.strategy import BacktestResult, Strategy
from src.models.trading import RiskLimit

router = APIRouter(prefix="/api/v1", tags=["portfolio"])


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
