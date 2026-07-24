"""Global Settings & Integrations endpoints (Phase 4 Epic E4.3), backing
Phase_7_Frontend_Architecture.md §2.4:

  - GET /settings/integrations         -- LLM provider + broker configuration status.
  - GET/POST/PATCH/DELETE /settings/notification-channels -- Telegram/Discord/etc. bot bindings.

Two very different trust levels live in this one screen, so they get very different treatment:

1. LLM provider keys (src/core/config.py) and broker credentials are read from `.env` via
   `get_settings()`, which is `@lru_cache`d -- the process reads `.env` once at startup and never
   again, so even if this router *could* write a new key to `.env`, nothing would pick it up
   without a restart. More importantly, `BrokerCredential` (DB-004) is explicitly documented as
   "Vault secret pointer only -- actual key material never lives in Postgres" (NFR-04), and no
   Vault client exists anywhere in this codebase yet (confirmed by grep). So this router only
   ever returns *masked* status (`configured: bool`, a last-4-chars hint) -- never a raw secret,
   never a write path for one. Building a "paste your API key here" form against a database that
   was explicitly designed to never hold key material, backed by a settings object that can't
   even be hot-reloaded, would be the wrong kind of real feature to fake into existing.
2. Notification channels (DB-002, `NotificationChannel`) carry no secrets at all -- a channel
   type, an external handle (e.g. a Telegram chat id), a verified flag, and a JSONB preferences
   blob for which alert levels route there. Confirmed unused before this router (exhaustive grep
   for `NotificationChannel(` found only the class definition) -- this part gets full real CRUD.

Notification channels are still scoped to "the first User row" the same way
src/api/routers/agents.py scopes Strategy creation to "the first Account row" -- adding real JWT
auth (this session) didn't add a multi-tenant data model to key channels off of the
*authenticated* user instead; that's a separate, larger refactor. What auth DID add: the three
mutating endpoints (create/update/delete) now require SystemAdministrator or PortfolioManager,
per Phase_12_Security_Design.md §2.2's "Configure omni-channel integrations" permission row.
"""

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.api.deps import require_role
from src.core.config import get_settings
from src.core.db import get_session
from src.core.security import ROLE_PORTFOLIO_MANAGER, ROLE_SYSTEM_ADMINISTRATOR
from src.models.user import NotificationChannel, User

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

_can_manage_channels = require_role(ROLE_SYSTEM_ADMINISTRATOR, ROLE_PORTFOLIO_MANAGER)

ALERT_LEVELS = ("critical_errors", "executed_trades", "risk_warnings", "strategy_promotions")
ChannelType = Literal["Telegram", "Discord", "WhatsApp", "Slack", "Email"]


def _mask(secret: str | None) -> str | None:
    if not secret:
        return None
    if len(secret) <= 4:
        return "•" * len(secret)
    return "••••" + secret[-4:]


# --- Integrations (read-only, masked) ----------------------------------------------------------


class ProviderStatus(BaseModel):
    name: str
    configured: bool
    masked_hint: str | None


class BrokerStatus(BaseModel):
    name: str
    configured: bool
    masked_hint: str | None
    sandbox: bool | None = None


class IntegrationsStatusResponse(BaseModel):
    llm_providers: list[ProviderStatus]
    brokers: list[BrokerStatus]
    editable: bool = Field(
        default=False,
        description=(
            "Always false: these are read from .env via a process-lifetime-cached Settings "
            "object, and broker credentials are designed to live in Vault (not Postgres, not "
            "this API) per DB-004's own documentation. Edit .env and restart the app instead."
        ),
    )


@router.get("/integrations", response_model=IntegrationsStatusResponse)
def get_integrations_status() -> IntegrationsStatusResponse:
    s = get_settings()
    llm_providers = [
        ProviderStatus(name="OpenAI", configured=bool(s.openai_api_key), masked_hint=_mask(s.openai_api_key)),
        ProviderStatus(name="Anthropic (Claude)", configured=bool(s.anthropic_api_key), masked_hint=_mask(s.anthropic_api_key)),
        ProviderStatus(name="DeepSeek", configured=bool(s.deepseek_api_key), masked_hint=_mask(s.deepseek_api_key)),
        ProviderStatus(name="Gemini", configured=bool(s.gemini_api_key), masked_hint=_mask(s.gemini_api_key)),
        ProviderStatus(name="HuggingFace", configured=bool(s.hf_token), masked_hint=_mask(s.hf_token)),
        ProviderStatus(name="OpenCode Zen", configured=bool(s.opencode_api_key), masked_hint=_mask(s.opencode_api_key)),
        ProviderStatus(name="Ollama", configured=True, masked_hint=s.ollama_base_url),
    ]
    brokers = [
        BrokerStatus(
            name="Zerodha (Kite Connect)",
            configured=bool(s.zerodha_api_key and s.zerodha_access_token),
            masked_hint=_mask(s.zerodha_access_token),
        ),
        BrokerStatus(
            name="Upstox",
            configured=bool(s.upstox_access_token),
            masked_hint=_mask(s.upstox_access_token),
            sandbox=s.upstox_use_sandbox,
        ),
    ]
    return IntegrationsStatusResponse(llm_providers=llm_providers, brokers=brokers)


# --- Notification channels (real CRUD) ---------------------------------------------------------


class NotificationChannelSummary(BaseModel):
    id: uuid.UUID
    channel_type: ChannelType
    external_handle: str
    is_verified: bool
    preferences: dict[str, Any]


class CreateNotificationChannel(BaseModel):
    channel_type: ChannelType
    external_handle: str
    alert_levels: list[str] = Field(default_factory=list)


class UpdateNotificationChannel(BaseModel):
    external_handle: str | None = None
    is_verified: bool | None = None
    alert_levels: list[str] | None = None


def _to_summary(channel: NotificationChannel) -> NotificationChannelSummary:
    return NotificationChannelSummary(
        id=channel.id,
        channel_type=channel.channel_type,  # type: ignore[arg-type]
        external_handle=channel.external_handle,
        is_verified=channel.is_verified,
        preferences=channel.preferences,
    )


def _first_user_id() -> uuid.UUID:
    with get_session() as session:
        user_id = session.scalars(select(User.id)).first()
    if user_id is None:
        raise HTTPException(
            status_code=409, detail="No user exists yet to own notification channels"
        )
    return user_id


@router.get("/notification-channels", response_model=list[NotificationChannelSummary])
def list_notification_channels() -> list[NotificationChannelSummary]:
    user_id = _first_user_id()
    with get_session() as session:
        channels = session.scalars(
            select(NotificationChannel).where(NotificationChannel.user_id == user_id)
        )
        return [_to_summary(c) for c in channels]


@router.post(
    "/notification-channels", response_model=NotificationChannelSummary, status_code=201
)
def create_notification_channel(
    body: CreateNotificationChannel, _user=Depends(_can_manage_channels)
) -> NotificationChannelSummary:
    user_id = _first_user_id()
    unknown = set(body.alert_levels) - set(ALERT_LEVELS)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown alert level(s): {sorted(unknown)}")

    with get_session() as session:
        channel = NotificationChannel(
            user_id=user_id,
            channel_type=body.channel_type,
            external_handle=body.external_handle,
            is_verified=False,
            preferences={"alert_levels": body.alert_levels},
        )
        session.add(channel)
        session.commit()
        session.refresh(channel)
        return _to_summary(channel)


@router.patch("/notification-channels/{channel_id}", response_model=NotificationChannelSummary)
def update_notification_channel(
    channel_id: uuid.UUID, body: UpdateNotificationChannel, _user=Depends(_can_manage_channels)
) -> NotificationChannelSummary:
    with get_session() as session:
        channel = session.get(NotificationChannel, channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Notification channel not found")
        if body.external_handle is not None:
            channel.external_handle = body.external_handle
        if body.is_verified is not None:
            channel.is_verified = body.is_verified
        if body.alert_levels is not None:
            unknown = set(body.alert_levels) - set(ALERT_LEVELS)
            if unknown:
                raise HTTPException(
                    status_code=422, detail=f"Unknown alert level(s): {sorted(unknown)}"
                )
            channel.preferences = {**channel.preferences, "alert_levels": body.alert_levels}
        session.commit()
        session.refresh(channel)
        return _to_summary(channel)


@router.delete("/notification-channels/{channel_id}", status_code=204)
def delete_notification_channel(channel_id: uuid.UUID, _user=Depends(_can_manage_channels)) -> None:
    with get_session() as session:
        channel = session.get(NotificationChannel, channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Notification channel not found")
        session.delete(channel)
        session.commit()
