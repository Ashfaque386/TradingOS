from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers.agents import router as agents_router
from src.api.routers.auth import router as auth_router
from src.api.routers.canvas import router as canvas_router
from src.api.routers.chat import router as chat_router
from src.api.routers.go_live_readiness import router as go_live_readiness_router
from src.api.routers.metrics import router as metrics_router
from src.api.routers.paper_trading import router as paper_trading_router
from src.api.routers.portfolio import router as portfolio_router
from src.api.routers.settings import router as settings_router
from src.api.routers.shadow_mode import router as shadow_mode_router
from src.api.routers.strategies import router as strategies_router
from src.api.routers.streams import router as streams_router
from src.api.routers.system import router as system_router
from src.api.routers.users import router as users_router
from src.observability.tracing import configure_tracing

app = FastAPI(title="TradingOS API", version="0.1.0")
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
app.include_router(users_router)
app.include_router(system_router)
app.include_router(streams_router)
app.include_router(metrics_router)
app.include_router(portfolio_router)
app.include_router(agents_router)
app.include_router(strategies_router)
app.include_router(settings_router)
app.include_router(chat_router)
app.include_router(canvas_router)
app.include_router(paper_trading_router)
app.include_router(shadow_mode_router)
app.include_router(go_live_readiness_router)
configure_tracing(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
