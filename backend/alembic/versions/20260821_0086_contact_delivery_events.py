"""contact_delivery_events — when an attempt reached somebody, not just whether.

Revision ID: 20260821_0086
Revises: 20260820_0085
Create Date: 2026-08-21

Mirrors sql/03_consent.sql. SQL is inlined so alembic does not depend on a
sibling Path read at upgrade time.

The reach estimator needs P(an attempt reaches a human) **by channel, hour and
borrower**. Three of those four words were already available and the fourth was
being thrown away.

* **WhatsApp receipts already arrive.** Meta posts sent / delivered / read /
  failed and ``db.record_whatsapp_delivery_status`` writes them to
  ``messages.delivery_status``, correctly refusing to let a late "sent" drag an
  already-read message backwards. But that column is a *current state*: a
  message that went sent → delivered → read leaves only "read", and the moment
  it was read — the one fact that distinguishes a borrower reachable at 09:00
  from one reachable at all — is overwritten and gone.

* **SMS had no receipts whatsoever.** ``twilio_sms.send`` returned the message
  SID, logged it, and dropped it, so nothing could ever be correlated back.

* **Voice was already fine.** ``features._reachability`` treats an interaction
  over twenty seconds as a connect, which is a better proxy than most
  production systems manage.

So this is an append-only log of transitions rather than a status column. One
row per event, with the instant it happened, which is what makes a hazard
fittable instead of a ratio.

The join to the attempt ledger already exists and is not recreated here:
``contact_events.related_id`` carries the message id for WhatsApp outbound, and
``idx_contact_events_related`` indexes it. Adding a second linkage would give
two answers to one question.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260821_0086"
down_revision: Union[str, Sequence[str], None] = "20260820_0085"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS contact_delivery_events (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
          channel TEXT NOT NULL CHECK (channel IN ('whatsapp','sms','email','voice')),
          provider TEXT NOT NULL,
          -- The provider's own id: a Meta wamid or a Twilio SID. This is what a
          -- replayed webhook is deduplicated on, so it is not optional in
          -- practice even though a hand-written row may omit it.
          provider_ref TEXT,
          -- What we sent, where the channel has a message object. Null for
          -- voice, whose connect evidence lives in interactions.
          message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
          -- Mirrors contact_events.related_id so an attempt and its receipts
          -- can be joined without inventing a second key.
          related_id TEXT,
          state TEXT NOT NULL CHECK (state IN (
            'queued','sent','delivered','read','failed','undelivered'
          )),
          reason TEXT,
          -- The provider's timestamp where it gives one, ours otherwise. The
          -- whole point of the table: 'read' without a time is a ratio, and
          -- 'read at 21:40' is a reach hazard.
          occurred_at timestamptz NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    # Replayed webhooks are normal, not exceptional — Meta and Twilio both
    # retry. One row per (provider_ref, state) makes a replay a no-op instead
    # of a second observation the reach model would count twice.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_contact_delivery_events_transition"
        " ON contact_delivery_events (provider, provider_ref, state)"
        " WHERE provider_ref IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_contact_delivery_events_tenant_id"
        " ON contact_delivery_events(tenant_id)"
    )
    # The reach trainer's read: every receipt for one borrower, in order.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_contact_delivery_events_customer"
        " ON contact_delivery_events (customer_id, channel, occurred_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_contact_delivery_events_related"
        " ON contact_delivery_events (related_id) WHERE related_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS contact_delivery_events")
