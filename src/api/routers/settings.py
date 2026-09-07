"""Global Settings & Integrations endpoints (Phase 4 Epic E4.3), backing
Phase_7_Frontend_Architecture.md §2.4:

  - GET /settings/integrations         -- LLM provider + broker configuration status.
  - GET/POST/PATCH/DELETE /settings/notification-channels -- Telegram/Discord/etc. bot bindings.

Two very different trust levels live in this one screen, so they get very different treatment:

1. LLM provider keys and broker credentials are both real, write-capable Vault-backed secrets
   (src/core/vault.py's `write_llm_provider_key`/`write_broker_credentials`, real since REL-002/
   REL-007) -- never read from `.env` directly by anything that resolves a key at call time.
   `src/agents/llm_router.py::resolve_api_key` and `src/brokers/factory.py` both check Vault
   first on every real call, falling back to the `.env`-sourced `Settings` object (still
   `@lru_cache`d, so a `.env` edit alone would need a restart -- Vault doesn't). UPDATE 2026-08-05
   (REL-021, correcting a stale claim in this docstring): "no Vault client exists anywhere in
   this codebase yet" was wrong even when this router stayed read-only for LLM keys -- the write
   endpoints below simply hadn't been built yet, matching what `broker_config.py` already did for
   brokers since REL-017. `GET /integrations` still only ever returns *masked* status
   (`configured: bool`, a last-4-chars hint), never a raw secret -- there is still no endpoint
   anywhere that reads a stored value back out, for either LLM keys or broker credentials, by
   design.
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
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.api.deps import require_role
from src.api.routers.risk_limits import _latest_risk_limit
from src.core import vault
from src.core.audit import write_audit_entry
from src.core.config import get_settings
from src.core.db import get_session
from src.core.security import ROLE_PORTFOLIO_MANAGER, ROLE_SYSTEM_ADMINISTRATOR
from src.data.reference.market_hours import IST, MARKET_CLOSE_MINUTES, MARKET_OPEN_MINUTES
from src.data.reference.nse_holiday_calendar import HOLIDAYS
from src.models.user import NotificationChannel, User

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

_can_manage_channels = require_role(ROLE_SYSTEM_ADMINISTRATOR, ROLE_PORTFOLIO_MANAGER)
_can_manage_llm_keys = require_role(ROLE_SYSTEM_ADMINISTRATOR, audit_denials=True)

# REL-021: the exact provider identifiers src/agents/llm_router.py::resolve_api_key /
# src/core/vault.py's llm-provider-keys/<provider> paths already use. "ollama" is deliberately
# excluded -- it's a local model server, never needs an API key (resolve_api_key returns None for
# it unconditionally).
LLM_PROVIDER_IDS = ("openai", "anthropic", "deepseek", "gemini", "huggingface", "opencode")

ALERT_LEVELS = ("critical_errors", "executed_trades", "risk_warnings", "strategy_promotions")
ChannelType = Literal["Telegram", "Discord", "Slack", "Email"]


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
            "Not read by anything today -- kept for API-shape stability. Both llm_providers and "
            "brokers are genuinely write-capable via dedicated endpoints (POST/DELETE "
            "/settings/llm-provider-keys/{provider}, /broker/credentials/{broker}) as of REL-021 "
            "-- a single flag on this combined response can't represent that per-category "
            "distinction, which is why the write forms gate on a real permission check "
            "(SystemAdministrator) client-side instead of this field."
        ),
    )


_PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "openai": "OpenAI",
    "anthropic": "Anthropic (Claude)",
    "deepseek": "DeepSeek",
    "gemini": "Gemini",
    "huggingface": "HuggingFace",
    "opencode": "OpenCode Zen",
}

_SETTINGS_FIELD_FOR_PROVIDER: dict[str, str] = {
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
    "deepseek": "deepseek_api_key",
    "gemini": "gemini_api_key",
    "huggingface": "hf_token",
    "opencode": "opencode_api_key",
}


@router.get("/integrations", response_model=IntegrationsStatusResponse)
def get_integrations_status() -> IntegrationsStatusResponse:
    s = get_settings()
    # REL-021: Vault-first, falling back to the .env-sourced Settings field -- same precedence
    # llm_router.py::resolve_api_key already uses for the real call, so this status grid reflects
    # a real write immediately instead of only ever showing the .env value.
    llm_providers = []
    for provider_id in LLM_PROVIDER_IDS:
        key = vault.read_llm_provider_key(provider_id) or getattr(
            s, _SETTINGS_FIELD_FOR_PROVIDER[provider_id]
        )
        llm_providers.append(
            ProviderStatus(
                name=_PROVIDER_DISPLAY_NAMES[provider_id],
                configured=bool(key),
                masked_hint=_mask(key),
            )
        )
    llm_providers.append(
        ProviderStatus(name="Ollama", configured=True, masked_hint=s.ollama_base_url)
    )
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


class RiskThresholds(BaseModel):
    scope_type: str
    max_daily_loss: float
    max_position_size_pct: float | None
    max_sector_exposure_pct: float | None
    max_drawdown_pct: float | None
    effective_from: datetime


class TradingCalendarSettings(BaseModel):
    timezone: str
    market_open_minutes: int
    market_close_minutes: int
    # Only the 3 fixed-date national holidays this codebase actually tracks (see
    # nse_holiday_calendar.py's own module docstring on the real, deliberate scope limit --
    # movable holidays like Diwali/Holi are not covered). Returned as an honest, real reflection
    # of HOLIDAYS, not a claim of full NSE calendar coverage.
    fixed_holidays: list[date]


class SystemSettingsResponse(BaseModel):
    risk_thresholds: RiskThresholds | None
    trading_calendar: TradingCalendarSettings
    # No feature-flag storage layer exists anywhere in this codebase today (confirmed: no
    # FeatureFlag model, no config table, no toggle mechanism beyond the unrelated per-agent
    # enable/disable state in AgentControlState). Returned honestly empty rather than fabricated.
    feature_flags: dict[str, bool]
    # NFR-04 (Genuinely Open items pass): "when was this credential last rotated" was previously
    # unanswerable anywhere in this codebase -- Phase_12_Security_Design.md's own rotation table
    # specifies a 60-day target for LLM keys with nothing tracking real elapsed time. `None` means
    # either Vault has nothing stored for it (resolved purely from `.env`, so no rotation history
    # exists to report) or Vault is unreachable -- indistinguishable, same as every other Vault
    # read in this codebase, never fabricated.
    credential_rotation: dict[str, str | None]


@router.get("", response_model=SystemSettingsResponse)
def get_system_settings() -> SystemSettingsResponse:
    """API-074. A composite, non-secret read of "current system configuration" -- real risk
    thresholds (reusing risk_limits.py's own _latest_risk_limit lookup, the same query
    GET /risk-limits/current already runs) and the real, hardcoded trading-calendar constants
    (src/data/reference/market_hours.py, nse_holiday_calendar.py). Deliberately does not fabricate
    a feature-flag system that doesn't exist in this codebase -- see SystemSettingsResponse's own
    docstring on that field."""
    credential_rotation: dict[str, str | None] = {
        provider_id: vault.read_llm_provider_key_rotated_at(provider_id)
        for provider_id in LLM_PROVIDER_IDS
    }
    # Same 2 real brokers get_integrations_status() above already reports on -- no broader
    # broker registry exists anywhere in this codebase to iterate instead.
    for broker in ("zerodha", "upstox"):
        credential_rotation[broker] = vault.read_broker_credentials_rotated_at(broker)

    with get_session() as session:
        limit = _latest_risk_limit(session)
        risk_thresholds = (
            RiskThresholds(
                scope_type=limit.scope_type,
                max_daily_loss=float(limit.max_daily_loss),
                max_position_size_pct=(
                    float(limit.max_position_size_pct)
                    if limit.max_position_size_pct is not None
                    else None
                ),
                max_sector_exposure_pct=(
                    float(limit.max_sector_exposure_pct)
                    if limit.max_sector_exposure_pct is not None
                    else None
                ),
                max_drawdown_pct=(
                    float(limit.max_drawdown_pct) if limit.max_drawdown_pct is not None else None
                ),
                effective_from=limit.effective_from,
            )
            if limit is not None
            else None
        )
        return SystemSettingsResponse(
            risk_thresholds=risk_thresholds,
            trading_calendar=TradingCalendarSettings(
                timezone=str(IST),
                market_open_minutes=MARKET_OPEN_MINUTES,
                market_close_minutes=MARKET_CLOSE_MINUTES,
                fixed_holidays=sorted(HOLIDAYS),
            ),
            feature_flags={},
            credential_rotation=credential_rotation,
        )


class VaultStatusResponse(BaseModel):
    reachable: bool
    kv_engine_mounted: bool | None
    vault_addr: str | None


@router.get("/vault/status", response_model=VaultStatusResponse)
def get_vault_status() -> VaultStatusResponse:
    """API-079 (REL-062). Real reachability, never a secret value -- open like every other plain
    status read in this router (`GET /integrations` above included)."""
    status = vault.vault_status()
    return VaultStatusResponse(
        reachable=status.reachable,
        kv_engine_mounted=status.kv_engine_mounted,
        vault_addr=status.vault_addr,
    )


class LlmProviderKeyRequest(BaseModel):
    api_key: str


@router.post("/llm-provider-keys/{provider}", status_code=204)
def set_llm_provider_key(
    provider: str,
    body: LlmProviderKeyRequest,
    _user: User = Depends(_can_manage_llm_keys),
) -> None:
    """REL-021 E21.1. Mirrors `broker_config.py::set_broker_credentials` exactly -- writes to the
    real Vault via `vault.write_llm_provider_key`, which `llm_router.py::resolve_api_key` already
    reads from first on every real LLM call, before falling back to `.env`. A 503 here means
    Vault is genuinely unreachable, not a fabricated success.

    UPDATE (Genuinely Open items, NFR-04): wrote no AuditLog row at all before now -- logs only
    the provider name, never the key value."""
    if provider not in LLM_PROVIDER_IDS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown provider '{provider}'. Must be one of {LLM_PROVIDER_IDS}.",
        )
    if not vault.write_llm_provider_key(provider, body.api_key):
        raise HTTPException(status_code=503, detail="Vault unreachable -- key not stored")
    with get_session() as session:
        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=_user.email,
            action="LLM_PROVIDER_KEY_ROTATED",
            entity_type="VaultSecret",
            after_state={"provider": provider},
        )
        session.commit()


@router.delete("/llm-provider-keys/{provider}", status_code=204)
def remove_llm_provider_key(provider: str, _user: User = Depends(_can_manage_llm_keys)) -> None:
    """REL-021 E21.1. Deletes the stored Vault key -- the next real call for this provider falls
    back to the `.env`-sourced `Settings` value (or fails clearly if none exists), matching
    `resolve_api_key`'s own fallback precedence."""
    if provider not in LLM_PROVIDER_IDS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown provider '{provider}'. Must be one of {LLM_PROVIDER_IDS}.",
        )
    vault.delete_llm_provider_key(provider)
    with get_session() as session:
        write_audit_entry(
            session,
            actor_type="Human",
            actor_id=_user.email,
            action="LLM_PROVIDER_KEY_REMOVED",
            entity_type="VaultSecret",
            after_state={"provider": provider},
        )
        session.commit()


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
        channel_type=channel.channel_type,
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


@router.post("/notification-channels", response_model=NotificationChannelSummary, status_code=201)
def create_notification_channel(
    body: CreateNotificationChannel, _user: User = Depends(_can_manage_channels)
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
    channel_id: uuid.UUID,
    body: UpdateNotificationChannel,
    _user: User = Depends(_can_manage_channels),
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
def delete_notification_channel(
    channel_id: uuid.UUID, _user: User = Depends(_can_manage_channels)
) -> None:
    with get_session() as session:
        channel = session.get(NotificationChannel, channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Notification channel not found")
        session.delete(channel)
        session.commit()
