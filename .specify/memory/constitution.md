# TradingOS Constitution

TradingOS is an enterprise AI trading operating system for the Indian equity and
F&O markets (NSE/BSE). This constitution defines the non-negotiable rules for how
the system is built and changed. It governs *process and engineering discipline*;
the detailed *domain* authority remains the design set in
`Project Document and BluePrint/` (SRS, ADR, LLD, AI Agent Design, ML
Architecture, Trading Engine Design, Frontend Architecture, DevOps Architecture,
API/Database/Security Design, Testing Strategy, Master Development Roadmap) and the
`TradingOS_ERDTM.xlsx` traceability workbook.

## Core Principles

### I. Spec-Driven & Traceable

Every non-trivial change MUST trace to (a) a requirement or decision in
`Project Document and BluePrint/` and (b) a roadmap epic / exit criterion in
`Phase_14_Master_Development_Roadmap.md`, recorded in `TradingOS_ERDTM.xlsx`.
New features MUST progress through the Spec Kit flow — specification → plan →
tasks → implementation — before code is written; bug fixes and tooling changes
MAY skip specification but MUST still name the REL epic or exit criterion they
serve. Commits that implement roadmap work use the `REL-NNN: <summary>` subject
convention; tooling/meta changes use `chore:` or `docs:`.

Rationale: the roadmap and ERDTM are the shared memory of a solo-maintained
system with a very large surface. Untraceable changes cannot be reviewed for
completeness or regression risk.

### II. Docker-Only Execution

All application code, tests, linters, type checks, database migrations, and
operational scripts MUST run inside the project's containers, invoked as
`docker compose run --rm app <command>` (or the documented `docker compose up`
services). No host-level Python, `venv`, or `pip` is used for project work. The
only sanctioned host-installed tools are `git`, the `pre-commit` orchestrator
(installed once per clone), and Ollama for local LLM inference via
`host.docker.internal:11434`. Dependency changes in `pyproject.toml` require
`docker compose build app`.

Rationale: a single reproducible runtime eliminates "works on my machine" drift
across the data layer (Postgres, DuckDB, Qdrant, Redis), Vault, Temporal, and
MinIO, and matches exactly what CI executes.

### III. Quality Gates Are Non-Negotiable

Ruff lint, Black format check, `mypy --strict`, Bandit SAST, and the gitleaks
secrets scan MUST pass at commit time (pre-commit) and in CI on every push to
`main`. CI additionally enforces `pip-audit` (dependency CVE scan), clean
`alembic upgrade head`, the full `pytest` suite, and the per-module coverage gate
(`scripts/module_coverage.py check`). Line length is 100; target is `py312`.
A gate MUST NOT be weakened, skipped, or `# noqa`/`# type: ignore`-suppressed
without an inline comment stating the specific, reviewed reason.

Rationale: these checks are the only automated reviewer this project has; a
disabled gate is an invisible regression.

### IV. Safety-Critical Trading Controls (NON-NEGOTIABLE)

The hardcoded Kill Switch (`src/engine/risk/`) and the Risk Manager are the most
safety-critical modules in the system. Changes to them MUST preserve fail-closed
behavior, keep the single system-wide kill-switch singleton, and target 100%
mutation-kill coverage per Testing Strategy TEST-002. Any new or modified
strategy MUST clear risk checks and run in paper/shadow mode before touching a
live-execution path. When an external dependency required for a safety decision
(Vault, broker, market-data) is unreachable, the system MUST fail closed — never
fail open into unguarded trading.

Rationale: a defect here can lose real money; every other principle yields to
containing that risk.

### V. Module Storage Ownership

Each of the four stores has exactly one owning module: Postgres is the relational
system of record (`src/models/`, `src/core/db.py`); DuckDB + Parquet is the
historical OHLCV data lake (`src/data/datalake/`); Qdrant is the agent memory /
RAG store (`src/memory/`); Redis is the live tick pub/sub bus
(`src/engine/live/`). No module reads from or writes to another module's store
directly. Cross-module access goes through the owning module's real interface
(`get_session()`, `DataLake`, the Qdrant client wrapper, the Redis tick
listener).

Rationale: implicit data crossing between stores destroys the ability to reason
about consistency, retention, and failure modes independently.

### VI. Real Integrations, Honest Status

Tests and CI MUST exercise real services and real seeded data (real Vault, real
Postgres/Qdrant/Redis, real historical OHLCV, real instrument master) rather than
stubs standing in for them. Work is marked done ONLY when its stated exit
criteria are actually met and verified. Known gaps MUST remain visibly
documented as gaps — via `continue-on-error`, a named `TODO`, or an explicit
"NOT yet satisfied" note — never silently closed or presented as passing.

Rationale: a fabricated green is worse than a red; the roadmap must reflect
reality to be usable.

### VII. Secrets Never in Source

No credentials, API keys, tokens, or private key/certificate material may appear
in tracked files. `.env`, `/certs/`, and `/vault/keys/` stay gitignored;
`.env.example` carries the documented shape only. Application signing uses Vault
Transit (`src/core/vault_transit.py`); RBAC is casbin policy-file driven. The
gitleaks scan runs git-aware over real history in both pre-commit and CI.

Rationale: a leaked key against real brokerage or infrastructure is an
unrecoverable incident.

## Technology & Architecture Constraints

- **Language / runtime**: Python `>=3.12`, executed only in the `python:3.12-slim`
  `app` image.
- **Core stack**: FastAPI + Uvicorn, SQLAlchemy 2.0, Pydantic v2 / pydantic-settings,
  Alembic, structlog structured logging.
- **Imports**: absolute, `src.`-prefixed (per `[tool.ruff.lint.isort]` config);
  this convention is deliberate and MUST NOT be traded away to satisfy tooling.
- **Schema changes**: every database change ships as an Alembic migration that
  applies cleanly from `head`; no out-of-band DDL.
- **Branching**: this repo uses a single `main` branch. CI runs on every push to
  `main`; the multi-branch GitFlow in the Testing Strategy is aspirational and
  not in force.
- **Design documents**: `Project Document and BluePrint/` and
  `TradingOS_ERDTM.xlsx` are local-edit-only reference material — never
  `git add`/`commit`/`push` them. Only `TradingOS/` code is committed.

## Development Workflow & Quality Gates

1. **Plan**: for a new feature, run `/speckit-specify` → `/speckit-plan` →
   `/speckit-tasks` (optionally `/speckit-clarify`, `/speckit-analyze`,
   `/speckit-checklist`) before implementation. Tie the work to its REL epic.
2. **Build**: implement inside the `app` container; keep changes scoped to the
   task list.
3. **Verify locally**: `pre-commit` (installed once per clone via host
   `pip install pre-commit && pre-commit install`) runs Ruff, Black,
   `mypy --strict`, Bandit, and gitleaks against the Docker `app` image on every
   commit. Run `docker compose run --rm app pytest` for affected areas.
4. **CI is the real gate**: every push to `main` runs the full lint/type/SAST/
   dependency/migration/test/coverage pipeline plus Cypress E2E and Helm lint.
   A change is not "landed" until that pipeline is green (mutation testing on the
   Risk Manager is `continue-on-error` pending an upstream `mutmut` fix and
   remains a tracked, unsatisfied gap).
5. **Record**: update `TradingOS_ERDTM.xlsx` and the roadmap status for the epic.

## Governance

This constitution supersedes ad-hoc practice. Where it and an older habit
conflict, this document wins; where it is silent, the design documents and ERDTM
govern domain decisions and this document's principles govern engineering
process.

- **Amendments** are made by a commit that edits this file, bumps the version per
  the policy below, and states the rationale in the commit message (and, during
  drafting, the Sync Impact Report comment).
- **Versioning policy** (of this constitution): MAJOR for backward-incompatible
  governance changes or principle removals/redefinitions; MINOR for a new
  principle/section or materially expanded guidance; PATCH for clarifications and
  wording fixes.
- **Compliance review**: every change is checked against these principles at
  review time. Added complexity or any deviation MUST be justified in writing in
  the plan or PR; an unjustified violation blocks the change.
- **Runtime guidance**: `README.md` is the onboarding entry point;
  `docs/TROUBLESHOOTING.md` covers local-stack gotchas.

**Version**: 1.0.0 | **Ratified**: 2026-09-10 | **Last Amended**: 2026-09-10
