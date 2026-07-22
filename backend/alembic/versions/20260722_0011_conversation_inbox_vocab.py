"""conversation inbox: status + sender vocabulary normalize

Drops viewer-relative `mine` as a stored conversation status (use
`assigned` + `assigned_user_id`; UI derives Mine via GET /me). Renames
message sender `human` → `agent` to match the Inbox screen vocabulary.

Revision ID: 20260722_0011
Revises: 20260722_0010
Create Date: 2026-07-22
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "20260722_0011"
down_revision: Union[str, Sequence[str], None] = "20260722_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- conversations.status: mine → assigned ---
    op.execute("ALTER TABLE conversations DROP CONSTRAINT IF EXISTS conversations_status_check")
    op.execute("UPDATE conversations SET status = 'assigned' WHERE status = 'mine'")
    op.execute(
        """
        UPDATE conversations
        SET status = 'bot'
        WHERE status IS NULL
           OR status NOT IN ('bot', 'needs_human', 'escalated', 'assigned')
        """
    )
    op.execute(
        """
        ALTER TABLE conversations
        ADD CONSTRAINT conversations_status_check
        CHECK (status IN ('bot', 'needs_human', 'escalated', 'assigned'))
        """
    )

    # --- messages.sender: human → agent ---
    op.execute("ALTER TABLE messages DROP CONSTRAINT IF EXISTS messages_sender_check")
    op.execute("UPDATE messages SET sender = 'agent' WHERE sender = 'human'")
    op.execute(
        """
        UPDATE messages
        SET sender = 'bot'
        WHERE sender IS NULL
           OR sender NOT IN ('customer', 'bot', 'agent', 'system')
        """
    )
    op.execute(
        """
        ALTER TABLE messages
        ADD CONSTRAINT messages_sender_check
        CHECK (sender IN ('customer', 'bot', 'agent', 'system'))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP CONSTRAINT IF EXISTS messages_sender_check")
    op.execute("UPDATE messages SET sender = 'human' WHERE sender = 'agent'")
    op.execute(
        """
        ALTER TABLE messages
        ADD CONSTRAINT messages_sender_check
        CHECK (sender IN ('customer', 'human', 'bot', 'system'))
        """
    )

    op.execute("ALTER TABLE conversations DROP CONSTRAINT IF EXISTS conversations_status_check")
    op.execute("UPDATE conversations SET status = 'mine' WHERE status = 'assigned'")
    op.execute(
        """
        ALTER TABLE conversations
        ADD CONSTRAINT conversations_status_check
        CHECK (status IN ('bot', 'needs_human', 'escalated', 'mine'))
        """
    )
