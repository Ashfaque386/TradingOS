"""Portfolio Manager Agent (AGT-016, PMPT-044/045, REL-010 E10.5).

Reads every real "Live"/"PaperTrading" Strategy's latest real BacktestResult plus the real
current broker margin (BrokerAdapter.get_margin()), asks the LLM for an advisory capital-weight
recommendation, and persists it as a `PortfolioAllocationRecommendation` row with
`status="Proposed"`. Never mutates any Strategy row, never places an order, never changes real
position sizing -- the human Portfolio Manager retains full override authority via
`accept`/`reject` (src/api/routers/portfolio.py), matching Business Rule 3.
"""

import json
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.agents.llm_router import complete
from src.agents.nodes.common import extract_json
from src.agents.prompt_registry import get_active_prompt
from src.brokers.base import BrokerAdapter
from src.models.portfolio_allocation_recommendation import PortfolioAllocationRecommendation
from src.models.strategy import BacktestResult, Strategy

PROMPT_SLUG = "portfolio_manager_agent"
TASK_PROMPT_SLUG = "portfolio_manager_agent_task"
logger = structlog.get_logger(__name__)

_ELIGIBLE_STATUSES = ("Live", "PaperTrading")


def _eligible_strategies_summary(session: Session) -> list[dict[str, str | float | None]]:
    strategies = list(
        session.scalars(select(Strategy).where(Strategy.status.in_(_ELIGIBLE_STATUSES)))
    )
    summary: list[dict[str, str | float | None]] = []
    for strat in strategies:
        if not strat.current_version_id:
            continue
        result = session.scalars(
            select(BacktestResult)
            .where(BacktestResult.strategy_version_id == strat.current_version_id)
            .order_by(BacktestResult.created_at.desc())
        ).first()
        sharpe_ratio = float(result.sharpe_ratio) if result and result.sharpe_ratio else None
        max_drawdown = float(result.max_drawdown) if result and result.max_drawdown else None
        cagr = float(result.cagr) if result and result.cagr else None
        summary.append(
            {
                "strategy_id": str(strat.id),
                "name": strat.name,
                "status": strat.status,
                "sharpe_ratio": sharpe_ratio,
                "max_drawdown": max_drawdown,
                "cagr": cagr,
            }
        )
    return summary


async def generate_allocation_recommendation(
    session: Session, broker: BrokerAdapter
) -> PortfolioAllocationRecommendation | None:
    """Returns `None` (not a fabricated recommendation) if there are no eligible strategies to
    allocate across, or if the LLM call/parse fails."""
    strategies_summary = _eligible_strategies_summary(session)
    if not strategies_summary:
        logger.warning("portfolio_manager_no_eligible_strategies")
        return None

    margin = await broker.get_margin()

    system_prompt = get_active_prompt(PROMPT_SLUG)
    user_prompt = get_active_prompt(TASK_PROMPT_SLUG).format(
        strategies_summary=json.dumps(strategies_summary),
        available_margin=margin.available_margin,
        used_margin=margin.used_margin,
    )

    try:
        response = complete(
            "orchestration",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        parsed = json.loads(extract_json(content))
        weights = parsed["weights"]
        rationale = str(parsed.get("rationale", ""))
    except Exception as exc:  # noqa: BLE001 - a bad LLM response degrades, never fabricates
        logger.warning("portfolio_manager_recommendation_failed", error=str(exc))
        return None

    recommendation = PortfolioAllocationRecommendation(
        generated_at=datetime.now(UTC),
        recommendations={"weights": weights},
        rationale=rationale,
        status="Proposed",
    )
    session.add(recommendation)
    session.commit()
    session.refresh(recommendation)
    return recommendation
