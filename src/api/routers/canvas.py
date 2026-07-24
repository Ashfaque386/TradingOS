"""The Live Canvas (Phase 4 Epic E4.3), backing Phase_7_Frontend_Architecture.md §2.5's
"interactive, side-by-side artifact viewer that dynamically renders charts, generated Python
code, backtest results, and risk matrices in real-time as the agents produce them."

A single composed read endpoint over data that's all real and already persisted elsewhere in
this codebase (StrategyVersion.python_code from src/api/routers/agents.py's
`_persist_strategy_progress`, BacktestResult from src/api/routers/strategies.py's real vectorbt
runs, AgentLog from the real graph-run wiring) -- nothing new is computed or fabricated here,
this just answers "what's the most recent real artifact of each kind, across every strategy/run,
right now" so the frontend doesn't need three separate polling loops with client-side
"which one is newest" logic. Risk data intentionally isn't duplicated here -- the frontend
already has real endpoints for that (portfolio.py's /risk-metrics, system.py's /kill-switch).
"""

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from src.core.db import get_session
from src.models.agent import AgentLog, AgentRun
from src.models.strategy import BacktestResult, Strategy, StrategyVersion

router = APIRouter(prefix="/api/v1/canvas", tags=["canvas"])


class LatestCode(BaseModel):
    strategy_id: uuid.UUID
    strategy_name: str
    version_no: int
    python_code: str
    validation_status: str
    created_at: datetime


class LatestBacktest(BaseModel):
    backtest_id: uuid.UUID
    strategy_id: uuid.UUID
    strategy_name: str
    sharpe_ratio: float | None
    max_drawdown: float | None
    total_trades: int | None
    has_equity_curve: bool
    created_at: datetime


class LatestAgentActivity(BaseModel):
    node: str
    message: str
    created_at: datetime


class CanvasStateResponse(BaseModel):
    latest_code: LatestCode | None
    latest_backtest: LatestBacktest | None
    latest_agent_activity: LatestAgentActivity | None


@router.get("/state", response_model=CanvasStateResponse)
def get_canvas_state() -> CanvasStateResponse:
    with get_session() as session:
        version = session.scalars(
            select(StrategyVersion).order_by(StrategyVersion.created_at.desc())
        ).first()
        latest_code = None
        if version is not None:
            strategy = session.get(Strategy, version.strategy_id)
            latest_code = LatestCode(
                strategy_id=version.strategy_id,
                strategy_name=strategy.name if strategy else "(deleted strategy)",
                version_no=version.version_no,
                python_code=version.python_code,
                validation_status=version.validation_status,
                created_at=version.created_at,
            )

        backtest = session.scalars(
            select(BacktestResult).order_by(BacktestResult.created_at.desc())
        ).first()
        latest_backtest = None
        if backtest is not None:
            backtest_version = session.get(StrategyVersion, backtest.strategy_version_id)
            strategy = (
                session.get(Strategy, backtest_version.strategy_id)
                if backtest_version is not None
                else None
            )
            latest_backtest = LatestBacktest(
                backtest_id=backtest.id,
                strategy_id=backtest_version.strategy_id if backtest_version else uuid.UUID(int=0),
                strategy_name=strategy.name if strategy else "(unknown strategy)",
                sharpe_ratio=backtest.sharpe_ratio,
                max_drawdown=backtest.max_drawdown,
                total_trades=backtest.total_trades,
                has_equity_curve=bool(backtest.equity_curve_path),
                created_at=backtest.created_at,
            )

        log = session.scalars(select(AgentLog).order_by(AgentLog.created_at.desc())).first()
        latest_activity = None
        if log is not None:
            run = session.get(AgentRun, log.agent_run_id)
            latest_activity = LatestAgentActivity(
                node=run.agent_name if run else "unknown",
                message=log.message,
                created_at=log.created_at,
            )

        return CanvasStateResponse(
            latest_code=latest_code,
            latest_backtest=latest_backtest,
            latest_agent_activity=latest_activity,
        )
