import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.agents.scheduler import build_scheduler
from src.api.routers.agents import router as agents_router
from src.api.routers.audit import router as audit_router
from src.api.routers.auth import router as auth_router
from src.api.routers.canvas import router as canvas_router
from src.api.routers.chat import router as chat_router
from src.api.routers.go_live_readiness import router as go_live_readiness_router
from src.api.routers.metrics import router as metrics_router
from src.api.routers.mfa import router as mfa_router
from src.api.routers.ml import router as ml_router
from src.api.routers.paper_trading import router as paper_trading_router
from src.api.routers.portfolio import router as portfolio_router
from src.api.routers.risk_limits import router as risk_limits_router
from src.api.routers.settings import router as settings_router
from src.api.routers.shadow_mode import router as shadow_mode_router
from src.api.routers.strategies import router as strategies_router
from src.api.routers.streams import router as streams_router
from src.api.routers.system import router as system_router
from src.api.routers.users import router as users_router
from src.api.routers.webhooks import router as webhooks_router
from src.core.config import get_settings
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
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
app.include_router(webhooks_router)
app.include_router(ml_router)
configure_tracing(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
