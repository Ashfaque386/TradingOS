"""Go-Live Readiness endpoint (Phase 4 Epic E4.4): reports the authoritative multi-condition
gate (src/engine/go_live_gate.py) for a single strategy, replacing the earlier fixed "2 weeks" /
"2 months" paper-trading duration figures. See Phase_14_Master_Development_Roadmap.md §5.4.
"""

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.core.db import get_session
from src.engine.go_live_gate import compute_readiness
from src.models.strategy import Strategy

router = APIRouter(prefix="/api/v1/go-live", tags=["go-live"])


class GateConditionResponse(BaseModel):
    label: str
    met: bool
    detail: str


class ReadinessResponse(BaseModel):
    strategy_id: uuid.UUID
    gate_met: bool
    conditions: list[GateConditionResponse]


@router.get("/readiness/{strategy_id}", response_model=ReadinessResponse)
def readiness(strategy_id: uuid.UUID) -> ReadinessResponse:
    with get_session() as session:
        strategy = session.get(Strategy, strategy_id)
        if strategy is None:
            raise HTTPException(status_code=404, detail=f"Strategy {strategy_id} not found")

        result = compute_readiness(session, strategy)
        return ReadinessResponse(
            strategy_id=strategy.id,
            gate_met=result.gate_met,
            conditions=[
                GateConditionResponse(label=c.label, met=c.met, detail=c.detail)
                for c in result.conditions
            ],
        )
