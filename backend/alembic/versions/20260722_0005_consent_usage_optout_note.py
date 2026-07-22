"""consent used_this_week + opt-out note

Persists weekly usage counters (resettable in the Consent drawer) and the
free-text note collected when logging an opt-out. Also widens optout_events
channel check to allow 'all' (screen shape).

Revision ID: 20260722_0005
Revises: 20260722_0004
Create Date: 2026-07-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_0005"
down_revision: Union[str, Sequence[str], None] = "20260722_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "channel_consents",
        sa.Column("used_this_week", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("optout_events", sa.Column("note", sa.Text(), nullable=True))
    op.execute("ALTER TABLE optout_events DROP CONSTRAINT IF EXISTS optout_events_channel_check")
    op.execute(
        """
        ALTER TABLE optout_events
        ADD CONSTRAINT optout_events_channel_check
        CHECK (channel IN ('voice','whatsapp','sms','email','chat','all'))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE optout_events DROP CONSTRAINT IF EXISTS optout_events_channel_check")
    op.execute(
        """
        ALTER TABLE optout_events
        ADD CONSTRAINT optout_events_channel_check
        CHECK (channel IN ('voice','whatsapp','sms','email','chat'))
        """
    )
    op.drop_column("optout_events", "note")
    op.drop_column("channel_consents", "used_this_week")
