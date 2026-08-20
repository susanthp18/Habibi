"""PTP pay-link: payment_intents + reminder kind + outbound template fields.

Revision ID: 20260812_0065
Revises: 20260812_0064
Create Date: 2026-08-12

A promise is the commitment. The money object is ``payment_intents`` — one
open intent per promise, unguessable public token, ledger settlement. Due
reminders reuse ``promise_reminders`` with ``kind='due'``. WhatsApp outbound
gains preview-url and utility-template columns so the existing SKIP LOCKED
queue can send a PTP confirm without blocking the voice thread on Graph.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_0065"
down_revision: Union[str, Sequence[str], None] = "20260812_0064"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "promise_reminders",
        sa.Column("kind", sa.Text(), nullable=False, server_default=sa.text("'due'")),
    )
    op.create_check_constraint(
        "ck_promise_reminders_kind",
        "promise_reminders",
        "kind IN ('confirm','due')",
    )
    op.create_index(
        "uq_promise_reminders_due",
        "promise_reminders",
        ["promise_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'due'"),
    )
    op.create_index(
        "idx_promise_reminders_due_drain",
        "promise_reminders",
        ["status", "scheduled_at"],
        postgresql_where=sa.text(
            "kind IN ('confirm','due') AND status IN ('queued','scheduled')"
        ),
    )

    op.add_column(
        "whatsapp_outbound_jobs",
        sa.Column(
            "preview_url",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("whatsapp_outbound_jobs", sa.Column("template_name", sa.Text(), nullable=True))
    op.add_column("whatsapp_outbound_jobs", sa.Column("template_lang", sa.Text(), nullable=True))
    op.add_column(
        "whatsapp_outbound_jobs",
        sa.Column("template_params", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.create_table(
        "payment_intents",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", sa.Text(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Text(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("promise_id", sa.Text(), sa.ForeignKey("promises.id", ondelete="SET NULL"), nullable=True),
        sa.Column("interaction_id", sa.Text(), sa.ForeignKey("interactions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False, server_default=sa.text("'INR'")),
        sa.Column("public_token", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False, server_default=sa.text("'hosted'")),
        sa.Column("provider_ref", sa.Text(), nullable=True),
        sa.Column("pay_url", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "ledger_entry_id",
            sa.Text(),
            sa.ForeignKey("ledger_entries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("confirm_channel", sa.Text(), nullable=True),
        sa.Column("suppression_reason", sa.Text(), nullable=True),
        sa.Column("phone_last4", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('created','sent','opened','paid','expired','failed','cancelled')",
            name="ck_payment_intents_status",
        ),
        sa.CheckConstraint(
            "provider IN ('hosted','razorpay')",
            name="ck_payment_intents_provider",
        ),
        sa.CheckConstraint(
            "confirm_channel IS NULL OR confirm_channel IN ('whatsapp','sms')",
            name="ck_payment_intents_confirm_channel",
        ),
    )
    op.create_index(
        "uq_payment_intents_public_token",
        "payment_intents",
        ["public_token"],
        unique=True,
    )
    op.create_index(
        "uq_payment_intents_open_promise",
        "payment_intents",
        ["promise_id"],
        unique=True,
        postgresql_where=sa.text(
            "promise_id IS NOT NULL AND status IN ('created','sent','opened')"
        ),
    )
    op.create_index("idx_payment_intents_tenant_id", "payment_intents", ["tenant_id"])
    op.create_index("idx_payment_intents_customer_id", "payment_intents", ["customer_id"])
    op.create_index("idx_payment_intents_promise_id", "payment_intents", ["promise_id"])
    op.create_index("idx_payment_intents_status", "payment_intents", ["status"])

    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_payment_intents_updated_at ON payment_intents;
        CREATE TRIGGER trg_payment_intents_updated_at
          BEFORE UPDATE ON payment_intents
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_payment_intents_updated_at ON payment_intents")
    op.drop_index("idx_payment_intents_status", table_name="payment_intents")
    op.drop_index("idx_payment_intents_promise_id", table_name="payment_intents")
    op.drop_index("idx_payment_intents_customer_id", table_name="payment_intents")
    op.drop_index("idx_payment_intents_tenant_id", table_name="payment_intents")
    op.drop_index("uq_payment_intents_open_promise", table_name="payment_intents")
    op.drop_index("uq_payment_intents_public_token", table_name="payment_intents")
    op.drop_table("payment_intents")
    op.drop_column("whatsapp_outbound_jobs", "template_params")
    op.drop_column("whatsapp_outbound_jobs", "template_lang")
    op.drop_column("whatsapp_outbound_jobs", "template_name")
    op.drop_column("whatsapp_outbound_jobs", "preview_url")
    op.drop_index("idx_promise_reminders_due_drain", table_name="promise_reminders")
    op.drop_index("uq_promise_reminders_due", table_name="promise_reminders")
    op.drop_constraint("ck_promise_reminders_kind", "promise_reminders", type_="check")
    op.drop_column("promise_reminders", "kind")
