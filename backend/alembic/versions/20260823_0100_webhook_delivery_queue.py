"""Turn webhook_deliveries into a real queue. Nothing ever delivered a webhook.

Revision ID: 20260823_0100
Revises: 20260822_0099
Create Date: 2026-08-23

Mirrors sql/10_admin.sql.

``webhook_endpoints``, ``webhook_subscriptions`` and ``webhook_deliveries``
shipped complete, the Integrations screen lists them, and the delivery log fills
with ``200 OK`` rows. All of it was a simulation: ``ops_screens.test_fire_webhook``
computed the latency from a SHA-256 digest of the endpoint id and wrote the
literal body ``{"ok":true,"mode":"simulated"}``. No HTTP client appeared anywhere
in the outbound webhook path. A tenant who registered an endpoint for
``promise.kept`` saw a healthy delivery log and never received a single event —
the failure mode that looks exactly like success.

``status='pending'`` and ``next_retry_at`` were already in the schema and were
written by nothing and read by nothing. They become the queue. Three columns are
added so a worker can claim a row the way every other queue in this codebase
does:

* ``locked_at`` / ``locked_by`` — the ``whatsapp_outbound_jobs`` claim
  convention, so a crashed worker's row is reclaimable instead of stuck.
* ``delivery_mode`` — ``live`` or ``simulated``. The test-fire button stays, and
  the demo it drives keeps working, but a simulated row now says so in the log
  instead of being indistinguishable from a delivery that actually happened.

The ``status`` CHECK is deliberately left alone. ``pending`` already covers "in
the queue", the client already renders all four values, and a fifth would ripple
through six components to say nothing new. An attempt chain that exhausts its
retry policy settles on ``server_err``/``client_err`` with ``next_retry_at``
cleared.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260823_0100"
down_revision: Union[str, Sequence[str], None] = "20260822_0099"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "webhook_deliveries",
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("webhook_deliveries", sa.Column("locked_by", sa.Text(), nullable=True))
    op.add_column(
        "webhook_deliveries",
        sa.Column(
            "delivery_mode",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'live'"),
        ),
    )
    op.create_check_constraint(
        "ck_webhook_deliveries_mode",
        "webhook_deliveries",
        "delivery_mode IN ('live','simulated')",
    )
    # Every row written before this migration came from the simulator.
    op.execute(
        "UPDATE webhook_deliveries SET delivery_mode = 'simulated' "
        "WHERE response_body LIKE '%\"mode\":\"simulated\"%'"
    )
    # The claim predicate, in the order the worker filters on.
    op.create_index(
        "idx_webhook_deliveries_claim",
        "webhook_deliveries",
        ["status", "next_retry_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_webhook_deliveries_claim", table_name="webhook_deliveries")
    op.drop_constraint("ck_webhook_deliveries_mode", "webhook_deliveries", type_="check")
    op.drop_column("webhook_deliveries", "delivery_mode")
    op.drop_column("webhook_deliveries", "locked_by")
    op.drop_column("webhook_deliveries", "locked_at")
