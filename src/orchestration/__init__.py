"""CEO-led AI trading organisation layer (spec 001-ceo-led-trading-org).

This package sits *above* `src/agents/graph.py`: it decomposes an objective into an
`OrganizationalPlan` of typed `Task`s with declared dependencies, runs independent tasks
concurrently and holds dependent ones until their inputs exist, records CEO decisions and
organisational events, and gates strategy deployment behind a real human approval. It reuses
the existing LangGraph pipeline, LLM router, SkillRegistry, sandbox, deterministic risk/
compliance engines, Qdrant memory, Redis pub/sub and Postgres -- it does not replace any of
them (constitution principle IV/V; spec FR-150).
"""
