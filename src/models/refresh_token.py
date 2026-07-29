import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDPKMixin


class RefreshToken(Base, UUIDPKMixin, TimestampMixin):
    """REL-007 E7.3 (SEC-012): single-use, rotated refresh tokens with session-family theft
    detection. `created_at` (TimestampMixin) doubles as "issued_at" -- a separate column would
    hold an identical value, since both are set at row-creation time; not duplicated.

    `token_hash` (SHA-256 of the raw token) is stored, never the raw value -- a fast hash is
    correct here (not bcrypt): the input is a `secrets.token_urlsafe(32)` high-entropy random
    value, not a low-entropy password, so there's no brute-force-guessing risk a slow hash would
    defend against.

    `family_id` stays constant across a whole rotation chain (`parent_id` links each new token
    back to the one it replaced) -- reusing an already-used or already-revoked token revokes
    every row sharing that `family_id`, not just the reused one, which is the actual theft-
    detection mechanism: an attacker who stole an old refresh token and a legitimate user who
    already rotated past it will both eventually present a `used_at`-set token, at which point
    the whole family (both the legitimate user's current token and anything the attacker holds)
    is killed and a real re-login is required.
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("refresh_tokens.id"), nullable=True
    )
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    revoked_reason: Mapped[str | None] = mapped_column(String(50))
