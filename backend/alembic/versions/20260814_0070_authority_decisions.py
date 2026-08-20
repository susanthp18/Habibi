"""P4 live authority matrix: the decision log.

Revision ID: 20260814_0070
Revises: 20260814_0069
Create Date: 2026-08-14

``authority_decisions`` is the append-only log, modelled on ``offer_decisions``
and ``treatment_decisions``. Every invocation is written, including escalate
and including shadow runs that never posted a rupee. A log holding only the
waivers we granted has no negative class in it.

Tenant-rooted, so ``rls.plan()`` derives an ordinary ``tenant_isolation``
policy with no special-casing.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260814_0070"
down_revision: Union[str, Sequence[str], None] = "20260814_0069"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "authority_decisions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=True),
        sa.Column("interaction_id", sa.Text(), nullable=True),
        sa.Column("dispute_id", sa.Text(), nullable=True),
        sa.Column("fee_type", sa.Text(), nullable=False),
        sa.Column("asked_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("feature_schema_version", sa.Text(), nullable=False),
        sa.Column(
            "features",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("approved_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("cap_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "reason_codes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("talk_track", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "enacted", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("enacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enacted_ref", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["interaction_id"], ["interactions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["dispute_id"], ["disputes.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "fee_type IN ('late_fee','bounce_charge','settlement','restructuring')",
            name="ck_authority_decisions_fee_type",
        ),
        sa.CheckConstraint(
            "mode IN ('off','shadow','live')",
            name="ck_authority_decisions_mode",
        ),
        sa.CheckConstraint(
            "verdict IN ('auto_approve','cap_inr','escalate')",
            name="ck_authority_decisions_verdict",
        ),
    )
    op.create_index(
        "idx_authority_decisions_tenant_id", "authority_decisions", ["tenant_id"]
    )
    op.create_index(
        "idx_authority_decisions_customer_id",
        "authority_decisions",
        ["customer_id"],
    )
    op.execute(
        """
        CREATE INDEX idx_authority_decisions_interaction
          ON authority_decisions (interaction_id, created_at DESC)
          WHERE interaction_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("idx_authority_decisions_interaction", table_name="authority_decisions")
    op.drop_index("idx_authority_decisions_customer_id", table_name="authority_decisions")
    op.drop_index("idx_authority_decisions_tenant_id", table_name="authority_decisions")
    op.drop_table("authority_decisions")
