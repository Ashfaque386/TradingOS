"""OPA/Casbin policy engine (REL-007 E7.5, SEC-017): replaces the plain-code
`role not in allowed_roles` check inside src/api/deps.py::require_role with a real policy file,
unit-testable and diffable in code review, per SEC-017's own stated rationale.

Casbin over OPA: the real policy surface (confirmed by exhaustive grep across every router) is 5
`require_role(...)` call sites covering 37 (role, route, method) grants across 11 distinct
endpoints -- too small to justify standing up an OPA sidecar as a new Docker Compose service.
Casbin is a pure-Python library, no new infrastructure.

Zero-call-site-diff design: every existing `require_role(ROLE_X, ROLE_Y, ...)` call site keeps
its exact source (src/api/deps.py's `_check` closure now asks this module instead of doing the
`in allowed_roles` check itself) -- see deps.py's own docstring for the drift-tripwire test that
keeps the `allowed_roles` arguments (no longer used for the actual decision) honest against
policy.csv.

Policy rows are keyed by FastAPI's resolved route *template* (e.g.
"/api/v1/strategies/{strategy_id}/promote", not the raw request URL with real IDs substituted in)
with exact string matching -- no glob/keyMatch. This removes a real class of policy-engine bug
(wildcard over-matching a route it shouldn't) at the cost of needing a new policy.csv row
whenever a new route is added, which is exactly the "diffable in code review" property SEC-017
asks for.
"""

from functools import lru_cache
from pathlib import Path

import casbin

_POLICY_DIR = Path(__file__).parent / "policy"
_MODEL_PATH = str(_POLICY_DIR / "model.conf")
_POLICY_PATH = str(_POLICY_DIR / "policy.csv")


@lru_cache
def _enforcer() -> casbin.Enforcer:
    return casbin.Enforcer(_MODEL_PATH, _POLICY_PATH)


def is_allowed(role: str, route_template: str, method: str) -> bool:
    return bool(_enforcer().enforce(role, route_template, method.upper()))
