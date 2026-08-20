"""Persist the channel a lead follow-up will actually use.

Revision ID: 20260814_0068
Revises: 20260813_0067
Create Date: 2026-08-14

The sheet always collected a channel (voice / WhatsApp / email / SMS) and the
API accepted it, then the INSERT dropped it and every list query hard-coded
``'voice'``. Consent re-checks and the next dial then used the wrong channel.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0068"
down_revision: Union[str, Sequence[str], None] = "20260813_0067"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "followups",
        sa.Column("channel", sa.Text(), nullable=False, server_default="voice"),
    )
    op.create_check_constraint(
        "ck_followups_channel",
        "followups",
        "channel IN ('voice','whatsapp','email','sms')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_followups_channel", "followups", type_="check")
    op.drop_column("followups", "channel")
