"""REL-009 E9.2 (NFR-05: "100% of LLM calls must be traced and logged via LangSmith") -- the
real, live verification the roadmap's exit criterion demands: a real `complete()` call genuinely
lands a trace in a real LangSmith project, and `fetch_langsmith_trace_url()` genuinely resolves a
real, working URL for it.

Skipped entirely unless LANGSMITH_API_KEY is configured, same pattern as the Kite Connect/Upstox
live-broker tests (tests/integration/test_kite_connect_live.py) -- this needs a real external
account, not something this test suite can fabricate.
"""

import pytest
from langsmith import Client

from src.agents.llm_router import complete, fetch_langsmith_trace_url, pop_last_langsmith_run_id
from src.core.config import get_settings

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not settings.langsmith_api_key,
    reason="LANGSMITH_API_KEY not configured -- see .env.example",
)


def test_a_real_complete_call_lands_a_real_trace_in_langsmith():
    complete("sentiment", messages=[{"role": "user", "content": "Reply with exactly: OK"}])

    run_id = pop_last_langsmith_run_id()
    assert run_id is not None, "complete() did not capture a run id -- tracing wiring is broken"

    # fetch_langsmith_trace_url() already retries against LangSmith's own real, observed
    # server-side indexing lag (confirmed empirically: an immediate, un-retried read_run() call
    # right after a synchronous batch POST can genuinely 404 for a moment) -- this IS the real
    # API call being verified, not a mock, so this is the whole test.
    trace_url = fetch_langsmith_trace_url(run_id)
    assert trace_url is not None, "a real run was sent but never became fetchable -- investigate"
    assert trace_url.startswith("https://smith.langchain.com/")
    assert run_id in trace_url

    # Independently confirm via a fresh direct read_run() (now that we know indexing settled)
    # that this is a genuinely real, fully-formed run record, not just a URL string.
    client = Client(api_key=settings.langsmith_api_key)
    run = client.read_run(run_id)
    assert run.id is not None
    assert run.session_id is not None  # LangSmith's internal id for the project this run is in
