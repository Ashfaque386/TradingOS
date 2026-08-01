"""Security response headers (REL-014 E14.2, GLH-03): closes the real, concrete finding from
the REL-009 E9.4 OWASP ZAP scan against `app-tls` -- "missing HSTS/CSP/X-Content-Type-Options/
Permissions-Policy/anti-clickjacking/CORP headers" -- documented there as a real gap, not fixed
in that pass. TradingOS's API is JSON-only (no server-rendered HTML except the deliberately
test-only `/_zap_test/reflect` endpoint), so the policy below is deliberately strict: nothing
here is expected to ever need relaxing for a real page this API serves.
"""

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# A pure JSON API has no legitimate use for framing, plugins, or loading its own responses as a
# scripted/styled subresource -- 'none' is not an arbitrary strict default here, it matches what
# this API actually does.
_CONTENT_SECURITY_POLICY = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"

# geolocation/camera/microphone/payment are never used by this API -- disabled outright rather
# than left to each browser's own default allowlist.
_PERMISSIONS_POLICY = "geolocation=(), camera=(), microphone=(), payment=()"

SECURITY_HEADERS: dict[str, str] = {
    # HSTS is meaningful only over HTTPS (the `app-tls` sibling service) -- browsers ignore it on
    # a plain-HTTP response by spec, so sending it unconditionally on `app`:8001 too is harmless,
    # not a false claim of transport security that port doesn't have.
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": _CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Permissions-Policy": _PERMISSIONS_POLICY,
    # Anti-clickjacking: CSP's frame-ancestors is the modern mechanism (above), X-Frame-Options
    # is kept alongside it for the handful of older browsers that don't honor frame-ancestors.
    "X-Frame-Options": "DENY",
    # 'same-site' (not 'same-origin'): the real Next.js dashboard is a genuinely different origin
    # (http://localhost:3000 / http://frontend:3000 vs. this API's own origin) by design -- see
    # main.py's CORSMiddleware comment. CORP governs cross-origin *no-cors subresource* loads
    # (img/script/etc.), not the CORS-mediated fetch() calls the dashboard actually makes, so
    # 'same-site' adds real defense-in-depth against arbitrary third-party embedding without
    # breaking the one legitimate cross-origin consumer this API has.
    "Cross-Origin-Resource-Policy": "same-site",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value
        return response
