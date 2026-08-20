"""P1 bounce-to-contact: payment_events case + pay-link FK.

Revision ID: 20260813_0067
Revises: 20260813_0066
Create Date: 2026-08-13

A NACH/UPI/ECS bounce is a first-class event. The row is the collections
case (open/in_progress project into work_items). payment_intents may hang
off a bounce the same way they hang off a PTP. Circular FKs: the event
points at the intent after send; the intent points at the event at create.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0067"
down_revision: Union[str, Sequence[str], None] = "20260813_0066"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_WORK_ITEMS_SQL = """
CREATE OR REPLACE VIEW work_items AS
SELECT
  'dispute'::TEXT AS entity_type,
  id AS entity_id,
  customer_id,
  assignee_user_id,
  status,
  priority,
  sla_due_at,
  'disputes'::TEXT AS source,
  created_at
FROM disputes
WHERE status IN ('new','under_review','awaiting_customer')
UNION ALL
SELECT
  'callback',
  id,
  customer_id,
  assignee_user_id,
  status,
  priority,
  COALESCE(sla_due_at, scheduled_at),
  'callbacks',
  created_at
FROM callbacks
WHERE status IN ('scheduled','reminded','in_progress','missed','rescheduled')
UNION ALL
SELECT
  'document_request',
  id,
  customer_id,
  assignee_user_id,
  status,
  priority,
  sla_due_at,
  'document_requests',
  created_at
FROM document_requests
WHERE status IN ('requested','generating','failed')
UNION ALL
SELECT
  'promise',
  id,
  customer_id,
  owner_user_id,
  status,
  CASE WHEN status IN ('broken','due_today') THEN 'high' ELSE 'normal' END,
  promised_at,
  'promises',
  created_at
FROM promises
WHERE status IN ('due_today','broken','partial')
UNION ALL
SELECT
  'lead',
  id,
  customer_id,
  owner_user_id,
  stage,
  priority,
  captured_at,
  'leads',
  created_at
FROM leads
WHERE stage IN ('interested','contacted','qualified')
UNION ALL
SELECT
  'followup',
  id,
  customer_id,
  assignee_user_id,
  status,
  priority,
  due_at,
  'followups',
  created_at
FROM followups
WHERE status IN ('open','in_progress','snoozed')
UNION ALL
SELECT
  'bounce',
  id,
  customer_id,
  assignee_user_id,
  status,
  'high',
  occurred_at + interval '48 hours',
  'payment_events',
  created_at
FROM payment_events
WHERE kind = 'bounce' AND status IN ('open','in_progress')
"""


def upgrade() -> None:
    op.create_table(
        "payment_events",
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
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "emi_installment_id",
            sa.Text(),
            sa.ForeignKey("emi_installments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("bounce_fee", sa.Numeric(14, 2), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("first_touch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_touch_channel", sa.Text(), nullable=True),
        sa.Column("next_voice_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_credit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "assignee_user_id",
            sa.Text(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("payment_intent_id", sa.Text(), nullable=True),
        sa.Column("suppression_reason", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint("kind IN ('bounce')", name="ck_payment_events_kind"),
        sa.CheckConstraint(
            "reason IN ('insufficient_funds','account_closed','mandate_expired','technical','unknown')",
            name="ck_payment_events_reason",
        ),
        sa.CheckConstraint(
            "source IN ('nach','upi','ecs','sandbox','webhook')",
            name="ck_payment_events_source",
        ),
        sa.CheckConstraint(
            "status IN ('open','in_progress','cured','suppressed')",
            name="ck_payment_events_status",
        ),
        sa.CheckConstraint(
            "first_touch_channel IS NULL OR first_touch_channel IN ('whatsapp','sms','voice')",
            name="ck_payment_events_first_touch_channel",
        ),
    )
    op.create_index(
        "uq_payment_events_source_ref",
        "payment_events",
        ["tenant_id", "source", "source_ref"],
        unique=True,
    )
    op.create_index(
        "uq_payment_events_open_emi",
        "payment_events",
        ["account_id", "emi_installment_id"],
        unique=True,
        postgresql_where=sa.text(
            "kind = 'bounce' AND status IN ('open','in_progress') "
            "AND emi_installment_id IS NOT NULL"
        ),
    )
    op.create_index("idx_payment_events_tenant_id", "payment_events", ["tenant_id"])
    op.create_index(
        "idx_payment_events_customer_occurred",
        "payment_events",
        ["customer_id", "occurred_at"],
    )
    op.create_index(
        "idx_payment_events_status_voice",
        "payment_events",
        ["status", "next_voice_at"],
    )
    op.create_index("idx_payment_events_account_id", "payment_events", ["account_id"])
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_payment_events_updated_at ON payment_events;
        CREATE TRIGGER trg_payment_events_updated_at
          BEFORE UPDATE ON payment_events
          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )

    op.add_column(
        "payment_intents",
        sa.Column(
            "payment_event_id",
            sa.Text(),
            sa.ForeignKey("payment_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "uq_payment_intents_open_event",
        "payment_intents",
        ["payment_event_id"],
        unique=True,
        postgresql_where=sa.text(
            "payment_event_id IS NOT NULL AND status IN ('created','sent','opened')"
        ),
    )
    op.create_index(
        "idx_payment_intents_payment_event_id",
        "payment_intents",
        ["payment_event_id"],
    )
    op.create_foreign_key(
        "fk_payment_events_intent",
        "payment_events",
        "payment_intents",
        ["payment_intent_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(_WORK_ITEMS_SQL)


def downgrade() -> None:
    op.execute(
        """
CREATE OR REPLACE VIEW work_items AS
SELECT
  'dispute'::TEXT AS entity_type,
  id AS entity_id,
  customer_id,
  assignee_user_id,
  status,
  priority,
  sla_due_at,
  'disputes'::TEXT AS source,
  created_at
FROM disputes
WHERE status IN ('new','under_review','awaiting_customer')
UNION ALL
SELECT
  'callback',
  id,
  customer_id,
  assignee_user_id,
  status,
  priority,
  COALESCE(sla_due_at, scheduled_at),
  'callbacks',
  created_at
FROM callbacks
WHERE status IN ('scheduled','reminded','in_progress','missed','rescheduled')
UNION ALL
SELECT
  'document_request',
  id,
  customer_id,
  assignee_user_id,
  status,
  priority,
  sla_due_at,
  'document_requests',
  created_at
FROM document_requests
WHERE status IN ('requested','generating','failed')
UNION ALL
SELECT
  'promise',
  id,
  customer_id,
  owner_user_id,
  status,
  CASE WHEN status IN ('broken','due_today') THEN 'high' ELSE 'normal' END,
  promised_at,
  'promises',
  created_at
FROM promises
WHERE status IN ('due_today','broken','partial')
UNION ALL
SELECT
  'lead',
  id,
  customer_id,
  owner_user_id,
  stage,
  priority,
  captured_at,
  'leads',
  created_at
FROM leads
WHERE stage IN ('interested','contacted','qualified')
UNION ALL
SELECT
  'followup',
  id,
  customer_id,
  assignee_user_id,
  status,
  priority,
  due_at,
  'followups',
  created_at
FROM followups
WHERE status IN ('open','in_progress','snoozed')
        """
    )
    op.drop_constraint("fk_payment_events_intent", "payment_events", type_="foreignkey")
    op.drop_index("idx_payment_intents_payment_event_id", table_name="payment_intents")
    op.drop_index("uq_payment_intents_open_event", table_name="payment_intents")
    op.drop_column("payment_intents", "payment_event_id")
    op.execute("DROP TRIGGER IF EXISTS trg_payment_events_updated_at ON payment_events")
    op.drop_index("idx_payment_events_account_id", table_name="payment_events")
    op.drop_index("idx_payment_events_status_voice", table_name="payment_events")
    op.drop_index("idx_payment_events_customer_occurred", table_name="payment_events")
    op.drop_index("idx_payment_events_tenant_id", table_name="payment_events")
    op.drop_index("uq_payment_events_open_emi", table_name="payment_events")
    op.drop_index("uq_payment_events_source_ref", table_name="payment_events")
    op.drop_table("payment_events")
