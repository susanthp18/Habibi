"""Allow voice-originated inbox conversations (escalate from Live CRM call).

Revision ID: 20260724_0033
Revises: 20260724_0032
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "20260724_0033"
down_revision: Union[str, Sequence[str], None] = "20260724_0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE conversations DROP CONSTRAINT IF EXISTS conversations_channel_check")
    op.execute(
        """
        ALTER TABLE conversations
        ADD CONSTRAINT conversations_channel_check
        CHECK (channel IN ('whatsapp', 'sms', 'email', 'chat', 'voice'))
        """
    )


def downgrade() -> None:
    op.execute(
        "UPDATE conversations SET channel = 'chat' WHERE channel = 'voice'"
    )
    op.execute("ALTER TABLE conversations DROP CONSTRAINT IF EXISTS conversations_channel_check")
    op.execute(
        """
        ALTER TABLE conversations
        ADD CONSTRAINT conversations_channel_check
        CHECK (channel IN ('whatsapp', 'sms', 'email', 'chat'))
        """
    )
