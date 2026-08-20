"""P7 live QA: decision log + whisper consume + barge audio result.

Revision ID: 20260814_0071
Revises: 20260814_0070
Create Date: 2026-08-14

``live_qa_decisions`` is the append-only log, same shape as authority and
treatment. Every failing turn is written, including shadow runs that never
took the call. A log holding only the barges we executed has no negative class.

``supervisor_actions.consumed_at`` lets the voice process drain a whisper once.
``audio_joined`` records whether Twilio actually took the media plane.

Tenant-rooted, so ``rls.plan()`` derives an ordinary ``tenant_isolation``
policy with no special-casing.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260814_0071"
down_revision: Union[str, Sequence[str], None] = "20260814_0070"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "live_qa_decisions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("customer_id", sa.Text(), nullable=True),
        sa.Column("account_id", sa.Text(), nullable=True),
        sa.Column("interaction_id", sa.Text(), nullable=True),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("feature_schema_version", sa.Text(), nullable=False),
        sa.Column(
            "features",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "reason_codes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "findings",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "enacted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
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
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["interaction_id"], ["interactions.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "mode IN ('off','shadow','live')",
            name="ck_live_qa_decisions_mode",
        ),
        sa.CheckConstraint(
            "verdict IN ('pass','fail_soft','fail_critical')",
            name="ck_live_qa_decisions_verdict",
        ),
        sa.CheckConstraint(
            "recommended_action IN ('none','listen','whisper','barge','inbox')",
            name="ck_live_qa_decisions_action",
        ),
    )
    op.create_index(
        "idx_live_qa_decisions_tenant_id", "live_qa_decisions", ["tenant_id"]
    )
    op.execute(
        """
        CREATE INDEX idx_live_qa_decisions_interaction
          ON live_qa_decisions (interaction_id, created_at DESC)
          WHERE interaction_id IS NOT NULL
        """
    )
    op.add_column(
        "supervisor_actions",
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "supervisor_actions",
        sa.Column(
            "audio_joined",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.execute(
        """
        INSERT INTO compliance_rules (id, tenant_id, code, label, severity, enabled)
        SELECT 'r-third', t.id, 'PROH-LANG-05', 'Unauthorized third-party disclosure', 'critical', true
        FROM tenants t
        WHERE NOT EXISTS (
          SELECT 1 FROM compliance_rules r
          WHERE r.id = 'r-third' AND r.tenant_id = t.id
        )
        """
    )


def downgrade() -> None:
    op.drop_column("supervisor_actions", "audio_joined")
    op.drop_column("supervisor_actions", "consumed_at")
    op.drop_index("idx_live_qa_decisions_interaction", table_name="live_qa_decisions")
    op.drop_index("idx_live_qa_decisions_tenant_id", table_name="live_qa_decisions")
    op.drop_table("live_qa_decisions")
