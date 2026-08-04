import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from src.agents.scheduler import build_scheduler
from src.api.routers.agents import router as agents_router
from src.api.routers.audit import observability_router
from src.api.routers.audit import router as audit_router
from src.api.routers.auth import router as auth_router
from src.api.routers.broker_config import router as broker_config_router
from src.api.routers.canvas import router as canvas_router
from src.api.routers.chat import router as chat_router
from src.api.routers.go_live_readiness import router as go_live_readiness_router
from src.api.routers.market_data import router as market_data_router
from src.api.routers.memory import router as memory_router
from src.api.routers.metrics import router as metrics_router
from src.api.routers.mfa import router as mfa_router
from src.api.routers.orders import router as orders_router
from src.api.routers.paper_trading import router as paper_trading_router
from src.api.routers.portfolio import router as portfolio_router
from src.api.routers.risk_limits import router as risk_limits_router
from src.api.routers.settings import router as settings_router
from src.api.routers.shadow_mode import router as shadow_mode_router
from src.api.routers.skills import router as skills_router
from src.api.routers.strategies import router as strategies_router
from src.api.routers.streams import router as streams_router
from src.api.routers.system import router as system_router
from src.api.routers.users import router as users_router
from src.api.routers.webhooks import router as webhooks_router
from src.core.config import get_settings
from src.core.security_headers import SecurityHeadersMiddleware
from src.core.vault import ensure_kv_engine
from src.core.vault_transit import VaultTransitUnavailableError, ensure_transit_key
from src.observability.tracing import configure_tracing

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # REL-007 E7.2: idempotent -- (re-)creates the Vault Transit JWT-signing key on every boot,
    # since dev Vault's in-memory storage means a `vault` container restart wipes it (see
    # vault_transit.py's module docstring). Self-heals login after a Vault wipe at the cost of a
    # forced global logout (every token signed by the deleted key stops verifying) -- logged
    # loudly, not silently swallowed, since an app that can't issue/verify tokens should be
    # obviously broken, not quietly broken.
    try:
        ensure_transit_key(get_settings())
    except VaultTransitUnavailableError as exc:
        logger.error(
            "Vault Transit setup failed at startup -- login will 503 until this is fixed: %s", exc
        )

    # REL-015 E15.1: real Vault server mode (unlike `-dev`) mounts no KV engine by default --
    # self-heals broker-credential/LLM-key/MFA/webhook-secret storage the same way the Transit
    # key above self-heals JWT signing. Fails open (logs, doesn't raise): every reader of this
    # engine already tolerates "nothing stored yet" and falls back to `.env` Settings, so a
    # failure here degrades to that same fallback rather than blocking boot.
    try:
        ensure_kv_engine(get_settings())
    except Exception as exc:  # noqa: BLE001 -- see comment above on why this fails open
        logger.error("Vault KV engine setup failed at startup: %s", exc)

    # REL-005 E5.6: the Scheduler Agent (AGT-025), started with the app rather than run as a
    # separate process -- an in-process APScheduler needs to live inside the same event loop
    # that's already running here. See src/agents/scheduler.py for why APScheduler over a
    # Temporal Schedule.
    # REL-007 E7.6: gated on run_scheduler so the sibling `app-tls` compose service (same image,
    # HTTPS-only) doesn't run a second copy of the daily research cycle alongside the primary
    # `app` service -- both processes share the same Postgres/Redis, so a double-fire would be a
    # real duplicate-trigger bug, not just wasted work.
    scheduler = None
    if get_settings().run_scheduler:
        scheduler = build_scheduler()
        scheduler.start()
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


app = FastAPI(title="TradingOS API", version="0.1.0", lifespan=lifespan)
# Dev-only: the Next.js dashboard (Phase 4 E4.3) runs on a different origin
# (http://localhost:3000) than this API (http://localhost:8001), so the browser needs CORS to
# call REST endpoints and open WebSocket connections here.
#
# REL-009 E9.6: "http://frontend:3000" is the SAME real frontend, reachable from a real browser
# running *inside* the `tradingos_default` docker network by its docker-network hostname instead
# of the host-exposed one -- confirmed as the actual root cause of every Cypress login-flow
# failure this session: a plain curl to the real API succeeded every time (curl doesn't enforce
# CORS), but the real browser's own fetch() call was silently blocked by this exact
# allow_origins list not including the origin Cypress's browser actually runs the page from,
# surfacing as the app's own generic "Incorrect email or password." catch-all error with no
# other visible symptom. Real E2E test traffic, not a security loosening -- both origins still
# resolve to the same real dev frontend, never a third party.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://frontend:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# REL-014 E14.2 (GLH-03): HSTS/CSP/X-Content-Type-Options/Permissions-Policy/X-Frame-Options/CORP
# on every real response -- the real gap the REL-009 E9.4 ZAP scan found and left open.
app.add_middleware(SecurityHeadersMiddleware)
app.include_router(auth_router)
app.include_router(mfa_router)
app.include_router(users_router)
app.include_router(system_router)
app.include_router(streams_router)
app.include_router(metrics_router)
app.include_router(portfolio_router)
app.include_router(risk_limits_router)
app.include_router(agents_router)
app.include_router(strategies_router)
app.include_router(settings_router)
app.include_router(chat_router)
app.include_router(canvas_router)
app.include_router(paper_trading_router)
app.include_router(shadow_mode_router)
app.include_router(go_live_readiness_router)
app.include_router(audit_router)
app.include_router(observability_router)
app.include_router(webhooks_router)
app.include_router(skills_router)
app.include_router(market_data_router)
app.include_router(broker_config_router)
app.include_router(memory_router)
app.include_router(orders_router)
configure_tracing(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


if get_settings().zap_test_endpoint_enabled:
    # REL-009 E9.4: see Settings.zap_test_endpoint_enabled's own docstring -- exists ONLY to
    # give the real OWASP ZAP CI job something real to find, proving the scan gate genuinely
    # detects a real vulnerability rather than just running and reporting zero findings. This
    # whole route is registered at import time, not per-request, so it's provably absent from
    # every real app boot where the flag is unset (the default everywhere except that one job).
    @app.get("/_zap_test/reflect", response_class=HTMLResponse)
    def _zap_test_reflect(q: str = "") -> str:
        return f"<html><body>You searched for: {q}</body></html>"  # deliberately unescaped
