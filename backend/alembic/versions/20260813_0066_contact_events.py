"""P6 contact policy: contact_events ledger + daily counters.

Revision ID: 20260813_0066
Revises: 20260812_0065
Create Date: 2026-08-13

Every outbound (bot, human, system) must pass contact_policy.admit() before
it leaves the building. The ledger is the source of truth for daily/weekly
caps; channel_consents.used_this_week is a cache. Append-only — no updated_at.
WhatsApp outbound jobs gain purpose/source so the SKIP LOCKED drain can
re-admit at send time with the same classification as enqueue.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0066"
down_revision: Union[str, Sequence[str], None] = "20260812_0065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contact_events",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Text(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            sa.Text(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Text(),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False, server_default=sa.text("'outbound'")),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("actor_kind", sa.Text(), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.Text(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("session_key", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("related_id", sa.Text(), nullable=True),
        sa.Column("touch_counted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "channel IN ('voice','whatsapp','sms','email','chat','field')",
            name="ck_contact_events_channel",
        ),
        sa.CheckConstraint(
            "direction IN ('outbound','inbound')",
            name="ck_contact_events_direction",
        ),
        sa.CheckConstraint(
            "purpose IN ('outreach','statutory','in_session')",
            name="ck_contact_events_purpose",
        ),
        sa.CheckConstraint(
            "actor_kind IN ('human','bot','system','agency')",
            name="ck_contact_events_actor_kind",
        ),
        sa.CheckConstraint(
            "outcome IN ('allowed','denied')",
            name="ck_contact_events_outcome",
        ),
    )
    op.create_index("idx_contact_events_tenant_id", "contact_events", ["tenant_id"])
    op.create_index(
        "idx_contact_events_customer_occurred",
        "contact_events",
        ["customer_id", "occurred_at"],
    )
    op.create_index(
        "idx_contact_events_session",
        "contact_events",
        ["customer_id", "session_key", "occurred_at"],
    )
    op.create_index(
        "idx_contact_events_related",
        "contact_events",
        ["customer_id", "source", "related_id"],
    )

    op.create_table(
        "contact_day_counters",
        sa.Column(
            "customer_id",
            sa.Text(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("outreach_sessions", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("customer_id", "local_date"),
    )

    op.add_column("whatsapp_outbound_jobs", sa.Column("purpose", sa.Text(), nullable=True))
    op.add_column("whatsapp_outbound_jobs", sa.Column("source", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("whatsapp_outbound_jobs", "source")
    op.drop_column("whatsapp_outbound_jobs", "purpose")
    op.drop_table("contact_day_counters")
    op.drop_index("idx_contact_events_related", table_name="contact_events")
    op.drop_index("idx_contact_events_session", table_name="contact_events")
    op.drop_index("idx_contact_events_customer_occurred", table_name="contact_events")
    op.drop_index("idx_contact_events_tenant_id", table_name="contact_events")
    op.drop_table("contact_events")
