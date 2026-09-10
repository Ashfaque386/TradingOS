"""Versioned system-prompt registry (Phase 2 E2.2; DB-backed since spec 001-ceo-led-trading-org
US6 / T075).

Prompts live both as plain-text files under ``src/agents/prompts/<slug>/v<N>.md`` (+
``registry.yaml``) and, since the ``d4f2a1c9e650`` seed migration, as rows in ``prompt_versions``.
``get_active_prompt`` reads the DB active row first and falls back to the file when there is no
DB row (or no DB at all) -- so nothing changed on seed, and a new version activated through the
Agent Settings API takes effect on the next agent run with no redeploy (FR-102/103/107).

A registry slug ending in ``_task`` / ``_chat`` maps to ``(agent_slug=<base>, kind=<task|chat>)``
in the DB; every other slug is ``kind="system"``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
import yaml

PROMPTS_DIR = Path(__file__).parent / "prompts"
REGISTRY_PATH = PROMPTS_DIR / "registry.yaml"
logger = structlog.get_logger(__name__)


class PromptNotFoundError(RuntimeError):
    pass


def _load_manifest() -> dict[str, Any]:
    with REGISTRY_PATH.open(encoding="utf-8") as f:
        manifest: dict[str, Any] = yaml.safe_load(f)
    return manifest


def resolve_slug(agent_slug: str, kind: str = "system") -> tuple[str, str]:
    """(registry slug, caller kind) -> (DB agent_slug, DB kind). Folds a ``_task`` / ``_chat``
    registry slug into the matching kind when the caller passed the default ``system``."""
    if kind == "system":
        for suffix, k in (("_task", "task"), ("_chat", "chat")):
            if agent_slug.endswith(suffix):
                return agent_slug[: -len(suffix)], k
    return agent_slug, kind


def _dir_slug(base: str, kind: str) -> str:
    return base if kind == "system" else f"{base}_{kind}"


def _active_content_from_db(base: str, kind: str) -> str | None:
    try:
        from sqlalchemy import select

        from src.core.db import get_session
        from src.models.agent_config import PromptVersion

        with get_session() as session:
            row = session.scalars(
                select(PromptVersion).where(
                    PromptVersion.agent_slug == base,
                    PromptVersion.kind == kind,
                    PromptVersion.is_active.is_(True),
                )
            ).first()
            return row.content if row is not None else None
    except Exception as exc:  # noqa: BLE001 -- any DB hiccup -> fall back to the file
        logger.debug("prompt_db_lookup_failed", agent_slug=base, kind=kind, error=str(exc))
        return None


def _active_version_from_file(dir_slug: str) -> int:
    manifest = _load_manifest()
    if dir_slug not in manifest:
        raise PromptNotFoundError(f"no registry entry for agent '{dir_slug}'")
    return int(manifest[dir_slug]["active_version"])


def get_active_prompt(agent_slug: str, kind: str = "system") -> str:
    base, resolved = resolve_slug(agent_slug, kind)
    db = _active_content_from_db(base, resolved)
    if db is not None:
        return db
    dir_slug = _dir_slug(base, resolved)
    version = _active_version_from_file(dir_slug)
    path = PROMPTS_DIR / dir_slug / f"v{version}.md"
    if not path.exists():
        raise PromptNotFoundError(f"prompt file missing: {path}")
    return path.read_text(encoding="utf-8").strip()


def get_prompt_id(agent_slug: str) -> str:
    manifest = _load_manifest()
    if agent_slug not in manifest:
        raise PromptNotFoundError(f"no registry entry for agent '{agent_slug}'")
    prompt_id: str = manifest[agent_slug]["prompt_id"]
    return prompt_id


def list_agents() -> dict[str, Any]:
    """The full manifest -- used by the Prompt Management Interface to list every registered
    agent, its prompt_id, and active version."""
    return _load_manifest()


def list_versions(agent_slug: str) -> list[int]:
    """Every ``v<N>.md`` file that exists on disk for this agent, sorted ascending."""
    agent_dir = PROMPTS_DIR / agent_slug
    if not agent_dir.is_dir():
        raise PromptNotFoundError(f"no prompt directory for agent '{agent_slug}'")
    versions = []
    for path in agent_dir.glob("v*.md"):
        try:
            versions.append(int(path.stem[1:]))
        except ValueError:
            continue
    return sorted(versions)


def get_prompt_version(agent_slug: str, version: int) -> str:
    """A specific version's content, regardless of which one is currently active."""
    path = PROMPTS_DIR / agent_slug / f"v{version}.md"
    if not path.exists():
        raise PromptNotFoundError(f"prompt file missing: {path}")
    return path.read_text(encoding="utf-8").strip()


def _db_set_active(base: str, kind: str, version: int) -> None:
    """Flip the single ``is_active`` row for ``(base, kind)`` to ``version``. Clears first, then
    flushes, then sets the new one -- the partial unique index never sees two active rows."""
    from sqlalchemy import select

    from src.core.db import get_session
    from src.models.agent_config import PromptVersion

    with get_session() as session:
        rows = list(
            session.scalars(
                select(PromptVersion).where(
                    PromptVersion.agent_slug == base, PromptVersion.kind == kind
                )
            ).all()
        )
        target = next((r for r in rows if r.version == version), None)
        if target is None:
            return
        for r in rows:
            if r.version != version:
                r.is_active = False
        session.flush()
        target.is_active = True
        session.commit()


def activate(agent_slug: str, kind: str, version: int, *, actor: str) -> None:
    """SA-only (enforced at the router). Make ``version`` the active prompt for
    ``(agent_slug, kind)``, clearing the prior active, and write an ``AuditLog`` before/after
    entry. Takes effect on the next agent run with no redeploy (FR-102/103)."""
    from sqlalchemy import select

    from src.core.audit import write_audit_entry
    from src.core.db import get_session
    from src.models.agent_config import PromptVersion

    base, resolved = resolve_slug(agent_slug, kind)
    with get_session() as session:
        rows = list(
            session.scalars(
                select(PromptVersion).where(
                    PromptVersion.agent_slug == base, PromptVersion.kind == resolved
                )
            ).all()
        )
        target = next((r for r in rows if r.version == version), None)
        if target is None:
            raise PromptNotFoundError(f"no prompt version {version} for '{base}' ({resolved})")
        before_active = next((r.version for r in rows if r.is_active), None)
        for r in rows:
            if r.version != version:
                r.is_active = False
        session.flush()
        target.is_active = True
        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=actor,
            action="PROMPT_VERSION_ACTIVATED",
            entity_type="PromptVersion",
            entity_id=target.id,
            before_state={"agent_slug": base, "kind": resolved, "active_version": before_active},
            after_state={"agent_slug": base, "kind": resolved, "active_version": version},
        )
        session.commit()
    logger.info("prompt_version_activated", agent_slug=base, kind=resolved, version=version)


def rollback(agent_slug: str, kind: str, *, actor: str) -> int:
    """Revert to the highest version below the current active one. Returns the version rolled
    back to; raises if there is nothing earlier to roll back to."""
    from sqlalchemy import select

    from src.core.db import get_session
    from src.models.agent_config import PromptVersion

    base, resolved = resolve_slug(agent_slug, kind)
    with get_session() as session:
        rows = list(
            session.scalars(
                select(PromptVersion).where(
                    PromptVersion.agent_slug == base, PromptVersion.kind == resolved
                )
            ).all()
        )
    current = next((r.version for r in rows if r.is_active), None)
    earlier = sorted(r.version for r in rows if current is None or r.version < current)
    if not earlier:
        raise PromptNotFoundError(f"no earlier prompt version to roll back to for '{base}'")
    target = earlier[-1]
    activate(base, resolved, target, actor=actor)
    return target


def set_active_version(agent_slug: str, version: int) -> None:
    """The file hot-swap write path (unchanged): flips ``active_version`` in ``registry.yaml``.
    Also syncs the DB active row so ``get_active_prompt`` (DB-first since US6) agrees."""
    manifest = _load_manifest()
    if agent_slug not in manifest:
        raise PromptNotFoundError(f"no registry entry for agent '{agent_slug}'")
    version_path = PROMPTS_DIR / agent_slug / f"v{version}.md"
    if not version_path.exists():
        raise PromptNotFoundError(f"prompt file missing: {version_path}")
    manifest[agent_slug]["active_version"] = version
    with REGISTRY_PATH.open("w", encoding="utf-8") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)
    base, kind = resolve_slug(agent_slug)
    try:
        _db_set_active(base, kind, version)
    except Exception as exc:  # noqa: BLE001 -- the file write is the source of truth for this path
        logger.warning("prompt_db_sync_failed", agent_slug=agent_slug, error=str(exc))
