# TradingOS

Enterprise AI Trading Operating System for the Indian equity & F&O markets (NSE/BSE).

Design source of truth: `../Project Document and BluePrint/` (SRS, ADR, LLD, AI Agent Design, ML Architecture, Trading Engine Design, Frontend Architecture, DevOps Architecture, API/Database/Security Design, Testing Strategy, Master Development Roadmap, and the `TradingOS_ERDTM.xlsx` traceability workbook).

## Status

REL-001 through REL-004 (Phase 9's original 4-phase/16-sprint scope) are complete and verified as of 2026-07-24. REL-005 through REL-011 are a roadmap extension covering the remaining gap surface (ML/RL platform, security hardening, observability, omni-channel messaging, and more) — see `Phase_14_Master_Development_Roadmap.md` for the full epic/exit-criteria breakdown and current status of each release.

## Data layer — Postgres, DuckDB, Qdrant, Redis

Four different stores, each doing one job:

- **Postgres** (`src/models/`, `src/core/db.py`) — the system of record: users, accounts, strategies/versions, trades, paper trades, shadow-mode attempts, backtest results, audit log, chat messages. Anything relational and transactional lives here.
- **DuckDB + Parquet** (`src/data/datalake/`) — the historical OHLCV data lake, partitioned `year/month/symbol.parquet` on disk and queried in-process via DuckDB (`src/data/datalake/query.py`). Read-heavy, columnar, no server to run — chosen over a time-series database for this scale.
- **Qdrant** (`src/memory/`) — the agent memory / RAG store: embedded strategy+outcome vectors for semantic retrieval (`trading_strategies` collection), so the Strategy Generator can query "what's worked or failed like this before."
- **Redis** — the live tick pub/sub bus (`src/engine/live/tick_listener.py`) feeding the execution pipeline; not used for durable storage.

No data crosses stores implicitly — each module owns exactly one of the four, and callers go through that module's real interface (`get_session()`, `DataLake`, the Qdrant client wrapper, the Redis tick listener) rather than reaching into another module's storage directly.

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
