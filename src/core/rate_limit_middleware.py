"""REL-064 (API-014): enforces src/core/api_rate_limit.py's counter on every request. Built the
same way src/core/security_headers.py::SecurityHeadersMiddleware is (BaseHTTPMiddleware,
dispatch awaits call_next then returns/decorates a response) -- but unlike SecurityHeaders, this
one can short-circuit before call_next, which makes its position in main.py's middleware stack
load-bearing, not cosmetic: it must be registered BEFORE CORSMiddleware (Starlette makes the
last-added middleware the outermost layer) so a 429 this middleware returns still bubbles up
through CORS and gets `Access-Control-Allow-Origin` etc. added -- registered after CORS instead,
a rate-limited cross-origin call from the real dashboard would see an opaque CORS failure, not a
readable 429 body.
"""

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.core.api_rate_limit import consume, unverified_subject
from src.core.config import get_settings
from src.memory.redis_client import get_redis_client

# Plain infra/health reads with no real per-caller "budget" concept -- excluded the same way
# webhook_rate_limit.py never touches non-webhook routes at all.
_EXEMPT_PATHS = frozenset({"/health", "/_zap_test/reflect"})


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        settings = get_settings()
        if not settings.api_rate_limit_enabled or request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        subject = unverified_subject(request.headers.get("Authorization"))
        client_host = request.client.host if request.client is not None else "unknown"
        caller_key = f"user:{subject}" if subject is not None else f"ip:{client_host}"

        result = consume(
            caller_key,
            redis_client=get_redis_client(),
            limit=settings.api_rate_limit_requests,
            window_seconds=settings.api_rate_limit_window_seconds,
        )
        if not result.allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(settings.api_rate_limit_window_seconds)},
            )
        return await call_next(request)
