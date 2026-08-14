"""Broker configuration & read endpoints (REL-010 E10.8b).

Permanently excludes any order-mutation route -- Business Rule 3 ("the system NEVER places a
real trade/order programmatically without explicit human action") is enforced here by the
absence of any order-placement/modification/cancellation call anywhere in this file, guarded by
a real, static grep-level regression test (see this router's own test file), the same discipline
src/api/routers/portfolio.py's E10.5 test applies to itself.

`/status` and `/order-book` are plain reads (ungated, matching every other broker read in this
codebase -- see market_data.py's module docstring). Writing/deleting a broker's stored Vault
credential is real credential management and stays SystemAdministrator-only.

UPDATE 2026-08-14 (REL-059): this module used to advertise itself as "API-051..060", a loose
range -- API-054..060 (order placement/cancel/detail, positions, portfolio margin/PnL) belong to
other routers (src/api/routers/orders.py, portfolio.py), not this file. This file's own real IDs
are API-051 (`GET /broker/status`), API-052 (`POST /broker/credentials/{broker}`), and API-053
(`GET /broker/order-book`) -- see each route's own docstring below. `DELETE
/broker/credentials/{broker}` has no dedicated ERDTM row at all; API-052's own note calls it out
as "a DELETE counterpart also added, beyond this spec row."
"""

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.deps import require_role
from src.brokers.base import OrderResponse
from src.brokers.factory import NoBrokerConfigured, build_broker
from src.core import vault
from src.core.security import ROLE_SYSTEM_ADMINISTRATOR
from src.models.user import User

router = APIRouter(prefix="/api/v1/broker", tags=["broker-config"])

_can_manage_broker_credentials = require_role(ROLE_SYSTEM_ADMINISTRATOR, audit_denials=True)


class BrokerStatusResponse(BaseModel):
    configured: bool
    broker_name: str | None
    detail: str | None = None


@router.get("/status", response_model=BrokerStatusResponse)
def broker_status() -> BrokerStatusResponse:
    """API-051. Whether `build_broker()` can real-construct an adapter right now (Vault or
    `.env` credentials present), and which adapter it resolved to -- not a live connectivity
    ping, just the same configuration check every other broker-backed endpoint already relies
    on."""
    try:
        broker = build_broker()
    except NoBrokerConfigured as exc:
        return BrokerStatusResponse(configured=False, broker_name=None, detail=str(exc))
    return BrokerStatusResponse(configured=True, broker_name=type(broker).__name__)


@router.get("/order-book", response_model=list[OrderResponse])
async def broker_order_book() -> list[OrderResponse]:
    """API-053 (previously mislabeled "API-052" here, which is actually
    `POST /broker/credentials/{broker}` -- see set_broker_credentials() below). Real live order
    book (read-only -- BrokerAdapter has no method to place, modify, or cancel an order anywhere
    in this codebase)."""
    try:
        broker = build_broker()
    except NoBrokerConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        return await broker.get_order_book()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502, detail=f"Broker order-book request failed: {exc}"
        ) from exc


class BrokerCredentialsRequest(BaseModel):
    credentials: dict[str, str]


@router.post("/credentials/{broker}", status_code=204)
def set_broker_credentials(
    broker: str,
    body: BrokerCredentialsRequest,
    _user: User = Depends(_can_manage_broker_credentials),
) -> None:
    """API-052 (previously mislabeled "API-053" here, which is actually `GET /broker/order-book`
    -- see broker_order_book() above). Writes to the real dev Vault via
    `write_broker_credentials` (already used by src/brokers/factory.py's Vault-first credential
    resolution) -- a 503 here means Vault is genuinely unreachable, not a fabricated success."""
    if not vault.write_broker_credentials(broker, body.credentials):
        raise HTTPException(status_code=503, detail="Vault unreachable -- credentials not stored")


@router.delete("/credentials/{broker}", status_code=204)
def remove_broker_credentials(
    broker: str, _user: User = Depends(_can_manage_broker_credentials)
) -> None:
    """Not tracked under its own API Traceability row -- API-052's own note calls this DELETE
    counterpart out as "added, beyond this spec row." Previously mislabeled "API-054" here, which
    is actually `POST /orders` (place an order; see src/api/routers/orders.py)."""
    vault.delete_broker_credentials(broker)
