# TradingOS

Enterprise AI Trading Operating System for the Indian equity & F&O markets (NSE/BSE).

Design source of truth: `../Project Document and BluePrint/` (SRS, ADR, LLD, AI Agent Design, ML Architecture, Trading Engine Design, Frontend Architecture, DevOps Architecture, API/Database/Security Design, Testing Strategy, Master Development Roadmap, and the `TradingOS_ERDTM.xlsx` traceability workbook).

## Status

Currently in **Dev Phase 1: Foundation & Data** (see `Phase_14_Master_Development_Roadmap.md` for epics, tasks, and exit criteria). Phase 1 must pass its exit criteria before Phase 2 (Agent Orchestration) work begins.

## Local development — everything runs in Docker

No local Python/venv/pip is used for this project — all commands run inside containers. The only thing expected to be installed on the host is Ollama (for local LLM inference, wired in from Phase 2 onward via `host.docker.internal:11434`).

```bash
docker compose up -d --build      # app, Postgres, Qdrant, Redis
docker compose run --rm app alembic upgrade head
docker compose run --rm app pytest
docker compose run --rm app ruff check src tests
docker compose run --rm app mypy src
```

The `app` service mounts the repo into the container and reloads on change, so day-to-day editing doesn't require rebuilding the image — only dependency changes in `pyproject.toml` do (`docker compose build app`).
