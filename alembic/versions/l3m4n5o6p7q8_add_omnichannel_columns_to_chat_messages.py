"""add channel/external_metadata/webhook_event_id to chat_messages (REL-010 E10.1)

Revision ID: l3m4n5o6p7q8
Revises: k2l3m4n5o6p7
Create Date: 2026-07-31 00:00:00.000000

Lets the dashboard chat pipeline (src/api/routers/chat.py, already real and tested) be reused
verbatim for Telegram/Discord replies (src/api/routers/webhooks.py) instead of a second
implementation. `channel` gets a server_default of 'Web' specifically so every row that already
exists (the entire pre-REL-010 dashboard chat history) is backfilled to the value that already
describes it, not left NULL -- `list_messages()`'s default `channel="Web"` filter then shows
exactly what it always showed, a real behavior-preservation guarantee, not an assumption.

`webhook_event_id` uses `ondelete="SET NULL"`, not CASCADE: `WebhookEvent`'s own docstring calls
it "30-day retention only -- operational debugging, not a system of record", while `ChatMessage`
is the actual durable conversation record. A real bug found running this epic's own test suite
against a live Postgres confirms why CASCADE (or no ondelete at all, the original version of
this migration) is wrong here: `tests/integration/test_webhooks_api.py`'s cleanup helper deletes
`WebhookEvent` rows after each test, and once a `ChatMessage` references one (this epic's own new
behavior), a plain FK with no `ondelete` raises a real `ForeignKeyViolation` -- confirmed via a
real failing test run, not a hypothetical. SET NULL preserves the real chat history and just
loses the cross-reference to the now-purged raw webhook payload, which is the behavior that
actually matches WebhookEvent's stated retention policy.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "l3m4n5o6p7q8"
down_revision: Union[str, None] = "k2l3m4n5o6p7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("channel", sa.String(length=20), nullable=False, server_default="Web"),
    )
    op.add_column(
        "chat_messages",
        sa.Column("external_metadata", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "chat_messages",
        sa.Column("webhook_event_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_chat_messages_webhook_event_id",
        "chat_messages",
        "webhook_events",
        ["webhook_event_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_chat_messages_webhook_event_id", "chat_messages", type_="foreignkey")
    op.drop_column("chat_messages", "webhook_event_id")
    op.drop_column("chat_messages", "external_metadata")
    op.drop_column("chat_messages", "channel")
