"""Versioned system-prompt registry (Phase 2 E2.2).

Prompts live as plain-text files under src/agents/prompts/<agent_slug>/v<N>.md.
registry.yaml maps each agent slug to its prompt_id and the currently active version.
Both are read fresh on every call (no import-time caching) so editing either file takes
effect on the next agent run without an app restart -- the "hot-swappable" requirement
from Phase_14 E2.2, pending the Phase 4 admin UI to edit them visually.
"""

from pathlib import Path
from typing import Any

import yaml

PROMPTS_DIR = Path(__file__).parent / "prompts"
REGISTRY_PATH = PROMPTS_DIR / "registry.yaml"


class PromptNotFoundError(RuntimeError):
    pass


def _load_manifest() -> dict[str, Any]:
    with REGISTRY_PATH.open(encoding="utf-8") as f:
        manifest: dict[str, Any] = yaml.safe_load(f)
    return manifest


def get_active_prompt(agent_slug: str) -> str:
    manifest = _load_manifest()
    if agent_slug not in manifest:
        raise PromptNotFoundError(f"no registry entry for agent '{agent_slug}'")
    version = manifest[agent_slug]["active_version"]
    path = PROMPTS_DIR / agent_slug / f"v{version}.md"
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
    """The full manifest -- used by the Phase 4 Prompt Management Interface
    (src/api/routers/agents.py) to list every registered agent, its prompt_id, and active
    version."""
    return _load_manifest()


def list_versions(agent_slug: str) -> list[int]:
    """Every v<N>.md file that exists on disk for this agent, sorted ascending -- not just the
    active one. An agent with only v1.md (true for all six agents today) returns `[1]`; nothing
    is fabricated to imply a version history that doesn't exist yet."""
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
    """A specific version's content, regardless of which one is currently active -- lets the
    admin UI preview a version before hot-swapping to it."""
    path = PROMPTS_DIR / agent_slug / f"v{version}.md"
    if not path.exists():
        raise PromptNotFoundError(f"prompt file missing: {path}")
    return path.read_text(encoding="utf-8").strip()


def set_active_version(agent_slug: str, version: int) -> None:
    """The hot-swap write path: flips `active_version` in registry.yaml. Takes effect on the
    very next `get_active_prompt()` call (no caching, see module docstring) -- no backend
    restart needed. Rewriting the whole file with `yaml.safe_dump` does lose the hand-written
    header comment above the manifest; that's an accepted trade-off for a straightforward
    read-modify-write rather than pulling in a comment-preserving YAML library for one field."""
    manifest = _load_manifest()
    if agent_slug not in manifest:
        raise PromptNotFoundError(f"no registry entry for agent '{agent_slug}'")
    version_path = PROMPTS_DIR / agent_slug / f"v{version}.md"
    if not version_path.exists():
        raise PromptNotFoundError(f"prompt file missing: {version_path}")
    manifest[agent_slug]["active_version"] = version
    with REGISTRY_PATH.open("w", encoding="utf-8") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)
