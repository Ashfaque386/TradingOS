"""SQLAlchemy models implementing Phase_11_Database_Design.md (DB-001..DB-018, PostgreSQL tables).

Import every model module here so Alembic's autogenerate sees the full metadata via Base.metadata.
"""

from src.models.account import Account, BrokerCredential
from src.models.agent import AgentLog, AgentRun
from src.models.audit import AuditLog
from src.models.base import Base
from src.models.chat import ChatMessage
from src.models.ml import MLModel
from src.models.paper_trading import PaperTrade
from src.models.shadow_mode import ShadowModeAttempt
from src.models.skill import AgentSkillMap, Skill
from src.models.strategy import BacktestResult, Strategy, StrategyVersion
from src.models.trading import Order, PortfolioPosition, RiskLimit, Trade
from src.models.user import NotificationChannel, User
from src.models.webhook import WebhookEvent

__all__ = [
    "Base",
    "User",
    "NotificationChannel",
    "Account",
    "BrokerCredential",
    "Strategy",
    "StrategyVersion",
    "BacktestResult",
    "Order",
    "Trade",
    "PortfolioPosition",
    "RiskLimit",
    "AgentRun",
    "AgentLog",
    "AuditLog",
    "Skill",
    "AgentSkillMap",
    "MLModel",
    "WebhookEvent",
    "ChatMessage",
    "PaperTrade",
    "ShadowModeAttempt",
]
