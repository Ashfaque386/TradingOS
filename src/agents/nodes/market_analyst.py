"""Market Analyst Agent node (AGT-002, PMPT-002) — Phase 2 Epic E2.3.

fetch_nse_sector_data / fetch_india_vix / query_macro_calendar are honestly-stubbed skills
(see src/agents/tools/skills.py) -- this node calls them defensively and notes their absence
in the prompt rather than fabricating figures, so the LLM's MarketContext output is explicit
about running with reduced data rather than silently inventing VIX/sector numbers.
"""

from typing import Any

import structlog

from src.agents.llm_router import complete
from src.agents.nodes.common import extract_json
from src.agents.prompt_registry import get_active_prompt
from src.agents.state import MarketContext, TradingOSGraphState
from src.agents.tools.registry import get_skill_registry
from src.agents.tools.skills import SkillNotImplementedError

PROMPT_SLUG = "market_analyst_agent"
TASK_PROMPT_SLUG = "market_analyst_agent_task"
MAX_RETRIES = 3
logger = structlog.get_logger(__name__)


def _try_skill(name: str, **kwargs: object) -> Any | None:
    try:
        return get_skill_registry().execute(name, **kwargs)
    except SkillNotImplementedError:
        return None


def market_analyst_node(state: TradingOSGraphState) -> dict[str, MarketContext]:
    system_prompt = get_active_prompt(PROMPT_SLUG)

    global_indices = _try_skill("fetch_global_indices")
    india_vix = _try_skill("fetch_india_vix")
    sector_data = _try_skill("fetch_nse_sector_data")
    macro_calendar = _try_skill("query_macro_calendar")
    missing = [
        name
        for name, value in [
            ("global indices", global_indices),
            ("India VIX", india_vix),
            ("sector data", sector_data),
            ("macro calendar", macro_calendar),
        ]
        if value is None
    ]

    directive = state.research_directive
    missing_summary = ", ".join(missing) if missing else "nothing -- all sources live"
    user_prompt = get_active_prompt(TASK_PROMPT_SLUG).format(
        directive_json=directive.model_dump_json() if directive else "none",
        missing_summary=missing_summary,
        schema=MarketContext.model_json_schema(),
    )

    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            response = complete(
                "research",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            content = response.choices[0].message.content
            context = MarketContext.model_validate_json(extract_json(content))
            return {"market_context": context}
        except Exception as exc:  # noqa: BLE001 - retry policy per Phase_4 §2 (3 retries)
            last_error = exc
            logger.warning("market_analyst_retry", attempt=attempt + 1, error=str(exc))

    raise RuntimeError(f"Market Analyst Agent failed after {MAX_RETRIES} retries") from last_error
