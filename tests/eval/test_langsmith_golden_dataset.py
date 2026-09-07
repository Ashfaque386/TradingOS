"""TEST-007: first real slice of the golden-dataset LLM eval harness (Phase_13_Testing_Strategy.md
section 2's target: >=95% pass rate on a curated golden dataset of market scenarios + expected
reasoning outputs, per versioned system prompt). Complete blank slate before this -- no
`langsmith.evaluate()` call, no dataset file, anywhere in this codebase.

Scoped to ONE prompt (Strategy Generator, PMPT-002/003) as the template for future prompts, not a
claim that the full SRS target is met by one prompt's worth of coverage. Uses the exact real
system/task prompts `src/agents/nodes/strategy_generator.py::strategy_generator_node` uses in
production -- a real LLM call, marked skip-unless-configured the same way
tests/integration/test_langsmith_live_trace.py already is, and deliberately NOT run as part of the
default fast suite (this repo's own convention for slow/real-LLM tests, matching
tests/integration/test_optuna_real_sandbox.py/test_real_backtest_runner.py).

`langsmith.evaluate()`'s real, installed-version behavior (confirmed empirically, not assumed from
its own docstring, which is misleading on this point): `data` as a plain list of dicts fails --
`AttributeError: 'dict' object has no attribute 'dataset_id'`/`'modified_at'` -- it genuinely
needs real `Example` rows already registered in a real LangSmith Dataset. `_ensure_golden_dataset`
below creates that dataset (and uploads the JSONL rows as real Examples) once, idempotently,
exactly the way a human would via the LangSmith UI, then `evaluate()` is called against the real
dataset NAME.

Deliberately does not call `get_skill_registry().execute("query_qdrant_strategy_memory", ...)`
for `past_strategies` (the real node's own live-Qdrant RAG lookup) -- a golden-dataset eval must
be reproducible against a fixed prompt input, not whatever this dev host's own Qdrant memory
happens to currently hold. A fixed, honest placeholder is used instead; extending this harness to
also vary `past_strategies` per scenario is a real follow-on, not attempted in this first slice.
"""

import json
from pathlib import Path

import pytest
from langsmith import Client, evaluate
from langsmith.schemas import Example, Run

from src.agents.llm_router import complete
from src.agents.nodes.common import extract_json
from src.agents.prompt_registry import get_active_prompt
from src.agents.state import MarketContext, ResearchDirective, StrategyLogic
from src.core.config import get_settings

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not settings.langsmith_api_key,
    reason="LANGSMITH_API_KEY not configured -- see .env.example",
)

_DATASET_PATH = Path(__file__).parent / "golden_dataset" / "strategy_generator.jsonl"
_DATASET_NAME = "tradingos-strategy-generator-golden"
_PROMPT_SLUG = "strategy_generator_agent"
_TASK_PROMPT_SLUG = "strategy_generator_agent_task"
_NO_PAST_STRATEGIES_PLACEHOLDER = "(no prior strategies retrieved for this golden-dataset run)"


def _load_dataset_rows() -> list[dict[str, object]]:
    with _DATASET_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _ensure_golden_dataset(client: Client) -> None:
    """Idempotent: uploads tests/eval/golden_dataset/strategy_generator.jsonl as real LangSmith
    Examples the first time this runs against a given LangSmith project; every later run reuses
    the same real dataset (matching the "reused, not re-created" convention this codebase already
    established for CI fixtures, e.g. scripts/seed_strategies_cypress_fixtures.py)."""
    if client.has_dataset(dataset_name=_DATASET_NAME):
        return
    dataset = client.create_dataset(
        _DATASET_NAME,
        description=(
            "TEST-007 golden dataset: real market-scenario inputs for the Strategy Generator "
            "Agent (PMPT-002/003), with the sectors/themes each scenario's own real "
            "ResearchDirective/MarketContext should surface in the generated strategy."
        ),
    )
    client.create_examples(dataset_id=dataset.id, examples=_load_dataset_rows())


def _predict(inputs: dict[str, object]) -> dict[str, object]:
    """The real target function `evaluate()` calls once per golden-dataset row -- builds the
    exact same system/task prompts strategy_generator_node uses in production, makes one real
    `complete()` call, and returns the parsed real response (or a real parse-failure marker,
    never fabricated)."""
    directive = ResearchDirective.model_validate(inputs["research_directive"])
    context = MarketContext.model_validate(inputs["market_context"])

    system_prompt = get_active_prompt(_PROMPT_SLUG)
    user_prompt = get_active_prompt(_TASK_PROMPT_SLUG).format(
        directive_json=directive.model_dump_json(),
        context_json=context.model_dump_json(),
        past_strategies=_NO_PAST_STRATEGIES_PLACEHOLDER,
        rejection_feedback="",
        schema=StrategyLogic.model_json_schema(),
    )

    response = complete(
        "coding",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    raw_content = response.choices[0].message.content
    try:
        strategy = StrategyLogic.model_validate_json(extract_json(raw_content))
    except Exception as exc:  # noqa: BLE001 -- a real parse/validation failure IS the result
        return {"parsed": False, "error": str(exc), "raw_content": raw_content}
    return {"parsed": True, **strategy.model_dump(mode="json")}


def _valid_strategy_logic(run: Run, example: Example) -> dict[str, object]:
    """The real, hard pass/fail floor: did the LLM's response actually validate against
    StrategyLogic's own schema at all? A prompt/schema drift regression fails this immediately,
    independent of the softer semantic check below."""
    outputs = run.outputs or {}
    return {"key": "valid_strategy_logic", "score": bool(outputs.get("parsed"))}


def _mentions_priority_sector_or_theme(run: Run, example: Example) -> dict[str, object]:
    """A real, objective, low-false-positive semantic check -- does the generated strategy's own
    hypothesis/entry_conditions text reference at least one of the scenario's own real priority
    sectors or strategy themes? Deliberately loose (not exact-string-match on the whole
    hypothesis) since the LLM's own phrasing legitimately varies run to run -- the SRS target is
    reasoning quality, not verbatim recall."""
    outputs = run.outputs or {}
    if not outputs.get("parsed"):
        return {"key": "mentions_priority_sector_or_theme", "score": False}
    haystack = " ".join(
        [str(outputs.get("hypothesis", "")), str(outputs.get("entry_conditions", ""))]
    ).lower()
    expected_outputs = example.outputs or {}
    expected = expected_outputs["expected_sectors_or_themes"]
    matched = any(term.lower() in haystack for term in expected)
    return {"key": "mentions_priority_sector_or_theme", "score": matched}


def test_strategy_generator_golden_dataset_eval() -> None:
    client = Client(api_key=settings.langsmith_api_key)
    _ensure_golden_dataset(client)
    dataset_size = len(_load_dataset_rows())

    results = evaluate(
        _predict,
        data=_DATASET_NAME,
        evaluators=[_valid_strategy_logic, _mentions_priority_sector_or_theme],
        experiment_prefix="tradingos-strategy-generator-golden",
        description="TEST-007 first slice: PMPT-002/003 Strategy Generator, real LLM calls",
        client=client,
    )

    valid_count = 0
    for row in results:
        for evaluation_result in row["evaluation_results"]["results"]:
            if evaluation_result.key == "valid_strategy_logic" and evaluation_result.score:
                valid_count += 1

    pass_rate = valid_count / dataset_size if dataset_size else 0.0
    # Reported, not asserted at the full SRS >=95% bar yet -- this is a first slice over 10
    # scenarios for one prompt, not the complete golden-dataset suite Phase_13 specifies. A real,
    # much lower floor (schema validity alone) proves the harness itself works end-to-end; a
    # future pass extending scenario count/prompt coverage is the right place to gate on 95%.
    print(f"\nStrategy Generator golden-dataset schema-validity pass rate: {pass_rate:.0%}")
    assert dataset_size > 0
    assert valid_count >= 1, (
        "not a single scenario produced a schema-valid StrategyLogic -- "
        "investigate a real regression, not a flaky LLM"
    )
