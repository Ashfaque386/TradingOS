"""Anti-drift tripwire (REL-007 E7.5, SEC-017): every `require_role(...)` call site still
declares its allowed roles as an argument (no longer used for the actual authorization decision,
which src/core/policy.py's Casbin enforcer now makes) purely so this test can catch drift
between what a call site *declares* and what policy.csv actually *grants* for the real routes it
guards. Walks the real, compiled FastAPI app -- not a hand-maintained list of routes, which would
itself be exactly the kind of thing that silently goes stale.
"""

from fastapi.routing import APIRoute, _IncludedRouter

from src.api.main import app
from src.core.policy import is_allowed
from src.core.security import ALL_ROLES


def _all_api_routes() -> list[APIRoute]:
    """FastAPI 0.140's `include_router` wraps each included router in a lazy `_IncludedRouter`
    rather than flattening its routes directly into `app.routes` (confirmed by inspection, not
    assumed) -- the real flat route list lives one level down, at
    `_IncludedRouter.original_router.routes`."""
    routes: list[APIRoute] = []
    for route in app.routes:
        if isinstance(route, _IncludedRouter):
            routes.extend(r for r in route.original_router.routes if isinstance(r, APIRoute))
        elif isinstance(route, APIRoute):
            routes.append(route)
    return routes


def _declared_roles_for_route(route: APIRoute) -> frozenset[str] | None:
    """Recursively walks a route's dependency tree for a callable carrying `declared_roles`
    (i.e. something built by src.api.deps.require_role). Returns None if the route has no
    require_role-based gate at all (e.g. a public GET)."""
    stack = list(route.dependant.dependencies)
    while stack:
        dependant = stack.pop()
        declared = getattr(dependant.call, "declared_roles", None)
        if declared is not None:
            return frozenset(declared)
        stack.extend(dependant.dependencies)
    return None


def test_every_require_role_gated_route_matches_policy_csv_exactly():
    checked = 0
    for route in _all_api_routes():
        declared_roles = _declared_roles_for_route(route)
        if declared_roles is None:
            continue  # not a require_role-gated route at all -- out of scope for this check

        for method in route.methods or []:
            if method == "HEAD":
                continue
            checked += 1
            for role in ALL_ROLES:
                expected = role in declared_roles
                actual = is_allowed(role, route.path, method)
                assert actual == expected, (
                    f"{role} on {method} {route.path}: require_role() declares "
                    f"{'allow' if expected else 'deny'} but policy.csv grants "
                    f"{'allow' if actual else 'deny'} -- policy.csv has drifted from the "
                    f"require_role(...) call site's declared roles."
                )

    # A real, non-zero number of routes were actually exercised -- guards against this test
    # silently checking nothing if route discovery ever breaks.
    assert checked >= 11
