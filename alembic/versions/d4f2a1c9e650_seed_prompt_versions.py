"""Seed prompt_versions from the current file-based prompts (spec 001-ceo-led-trading-org, T074).

Imports every ``src/agents/prompts/<slug>/vN.md`` plus ``registry.yaml`` into ``prompt_versions``
with ``is_active`` matching the file registry's ``active_version``. A registry slug ending in
``_task`` / ``_chat`` is folded into ``(agent_slug=<base>, kind=<task|chat>)``; everything else is
``kind="system"``. **No behaviour change** -- ``get_active_prompt`` reads exactly the same text it
read before, now from the DB with a file fallback (research R12).

Revision ID: d4f2a1c9e650
Revises: c7e1d9a4b820
Create Date: 2026-09-11
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
import yaml
from alembic import op

revision: str = "d4f2a1c9e650"
down_revision: str | None = "c7e1d9a4b820"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "src" / "agents" / "prompts"

_prompt_versions = sa.table(
    "prompt_versions",
    sa.column("id", sa.UUID()),
    sa.column("agent_slug", sa.String()),
    sa.column("kind", sa.String()),
    sa.column("version", sa.Integer()),
    sa.column("content", sa.Text()),
    sa.column("author", sa.String()),
    sa.column("change_summary", sa.Text()),
    sa.column("is_active", sa.Boolean()),
    sa.column("created_at", sa.DateTime()),
)


def _split(slug: str) -> tuple[str, str]:
    for suffix, kind in (("_task", "task"), ("_chat", "chat")):
        if slug.endswith(suffix):
            return slug[: -len(suffix)], kind
    return slug, "system"


def upgrade() -> None:
    manifest_path = _PROMPTS_DIR / "registry.yaml"
    manifest: dict[str, dict[str, object]] = yaml.safe_load(manifest_path.read_text("utf-8"))
    now = datetime.now(UTC)
    rows: list[dict[str, object]] = []
    for slug, entry in manifest.items():
        active = int(entry["active_version"])  # type: ignore[call-overload]
        base, kind = _split(slug)
        agent_dir = _PROMPTS_DIR / slug
        for path in sorted(agent_dir.glob("v*.md")):
            try:
                version = int(path.stem[1:])
            except ValueError:
                continue
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "agent_slug": base,
                    "kind": kind,
                    "version": version,
                    "content": path.read_text("utf-8").strip(),
                    "author": "seed:d4f2a1c9e650",
                    "change_summary": "Seeded from the file-based prompt registry (T074).",
                    "is_active": version == active,
                    "created_at": now,
                }
            )
    if rows:
        op.bulk_insert(_prompt_versions, rows)


def downgrade() -> None:
    op.execute("DELETE FROM prompt_versions WHERE author = 'seed:d4f2a1c9e650'")
