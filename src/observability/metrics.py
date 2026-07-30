"""Prometheus metrics (Phase 4 Epic E4.2 + REL-009 E9.1), per Phase_8_DevOps_Architecture.md §5
("Metrics: Prometheus & Grafana") and Phase_9_Master_Implementation_Guide.md §5 Risk Register:
"Prometheus alerts if WebSocket latency > 100ms."
"""

from prometheus_client import Gauge, Histogram

WS_STREAM_LATENCY_SECONDS = Histogram(
    "tradingos_ws_stream_latency_seconds",
    "Latency (seconds) of relaying a message through a TradingOS WebSocket stream endpoint",
    labelnames=("stream",),
)

# REL-009 E9.1: real per-node LangGraph execution duration, observed in
# src/api/routers/agents.py::_execute_graph_run.
AGENT_RUN_DURATION_SECONDS = Histogram(
    "tradingos_agent_run_duration_seconds",
    "Wall-clock duration of a single LangGraph agent node's execution",
    labelnames=("agent_name",),
)

# REL-009's ML_TRAINING_DURATION_SECONDS metric (src/ml/training/orchestrator.py) was removed
# 2026-07-30 alongside the rest of the ML/RL platform (Phase 5), disabled pending a host
# resource upgrade -- see Phase_5_Machine_Learning_Architecture.md's own status banner.

# REL-009 E9.1: real per-tick dispatch latency (tick receipt -> handoff to the broker adapter),
# the same NFR-02 quantity test_nfr02_real_broker_latency.py measures point-in-time -- this makes
# it a real, continuously scraped metric instead of only a one-off test assertion. Observed in
# src/engine/live/execution_pipeline.py::ExecutionPipeline.handle_tick.
ORDER_EXECUTION_LATENCY_SECONDS = Histogram(
    "tradingos_order_execution_latency_seconds",
    "Latency (seconds) from tick receipt to broker adapter handoff (NFR-02)",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, float("inf")),
)

# REL-009 (2026-07-30): real cumulative HuggingFace token usage tracked so far today (UTC),
# observed in src/agents/llm_router.py::_HFUsageTracker.record -- lets the real usage-budget
# guard (Settings.hf_daily_token_budget) be watched on the E9.1 Grafana dashboard instead of
# only being visible in logs when it trips.
HF_TOKENS_USED_TODAY = Gauge(
    "tradingos_hf_tokens_used_today",
    "Real cumulative HuggingFace Inference token usage tracked so far today (UTC)",
)
