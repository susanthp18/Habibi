"""P3 next-best-treatment: the decision log and the holds that veto it.

Revision ID: 20260814_0069
Revises: 20260814_0068
Create Date: 2026-08-14

Two tables, for the two halves of a gated engine.

``treatment_decisions`` is the append-only log, modelled on ``offer_decisions``.
Every invocation is written, **including the ones that decided to do nothing**
and including shadow runs that were never enacted. A log holding only the
actions we took has no negative class in it: it cannot train a model and it
cannot answer "why did the engine go quiet on Tuesday?". The roadmap's exit
criterion for this feature is a fortnight of shadow logs with a suppression
breakdown, and this table is that breakdown.

``treatment_holds`` is the veto nobody had a home for. Hardship, an open
dispute, a regulatory complaint, bereavement and a matter with legal are all
reasons to stop dunning someone, and all five lived as prose in the policy
corpus or as a routing rule that fired only if a human was already on the call.
A hold is a row, so a bot at 02:00 is bound by it exactly as a supervisor is.

Both are tenant-rooted, so ``rls.plan()`` derives an ordinary
``tenant_isolation`` policy for them with no special-casing.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260814_0069"
down_revision: Union[str, Sequence[str], None] = "20260814_0068"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "treatment_holds",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("customer_id", sa.Text(), nullable=False),
        # Nullable: hardship is a person, a dispute is usually one account.
        sa.Column("account_id", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False, server_default="manual"),
        sa.Column("interaction_id", sa.Text(), nullable=True),
        sa.Column("placed_by_user_id", sa.Text(), nullable=True),
        sa.Column("specialist_user_id", sa.Text(), nullable=True),
        sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "starts_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by_user_id", sa.Text(), nullable=True),
        sa.Column("released_reason", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["interaction_id"], ["interactions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["placed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["specialist_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["released_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "kind IN ('hardship','dispute','complaint','bereavement','legal')",
            name="ck_treatment_holds_kind",
        ),
        sa.CheckConstraint(
            "source IN ('manual','bot','system','regulator')",
            name="ck_treatment_holds_source",
        ),
    )
    op.create_index(
        "idx_treatment_holds_tenant_id", "treatment_holds", ["tenant_id"]
    )
    op.create_index(
        "idx_treatment_holds_customer_id", "treatment_holds", ["customer_id"]
    )
    # The engine's hot read: every active hold for one customer.
    op.execute(
        """
        CREATE INDEX idx_treatment_holds_active
          ON treatment_holds (customer_id, kind)
          WHERE released_at IS NULL
        """
    )
    # One live hold per (customer, account, kind). COALESCE because a NULL
    # account_id is "the whole customer", and Postgres would otherwise treat
    # two customer-level hardship holds as distinct rows.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_treatment_holds_active
          ON treatment_holds (customer_id, COALESCE(account_id, ''), kind)
          WHERE released_at IS NULL
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_treatment_holds_updated_at
        BEFORE UPDATE ON treatment_holds
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )

    op.create_table(
        "treatment_decisions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=True),
        sa.Column("interaction_id", sa.Text(), nullable=True),
        sa.Column("trigger_kind", sa.Text(), nullable=False),
        sa.Column("trigger_ref", sa.Text(), nullable=True),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("variant", sa.Text(), nullable=True),
        sa.Column("recommender", sa.Text(), nullable=False),
        sa.Column("recommender_version", sa.Text(), nullable=False),
        sa.Column("feature_schema_version", sa.Text(), nullable=False),
        sa.Column(
            "features",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "candidates",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "excluded",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("chosen_action", sa.Text(), nullable=True),
        sa.Column("chosen_channel", sa.Text(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expected_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("suppression_reason", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "enacted", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("enacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enacted_ref", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("outcome_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "trigger_kind IN ('bounce','broken_ptp','pre_due','dpd_tick',"
            "'inbound','manual','no_contact','wrap_up')",
            name="ck_treatment_decisions_trigger",
        ),
        sa.CheckConstraint(
            "mode IN ('off','shadow','live')", name="ck_treatment_decisions_mode"
        ),
        sa.CheckConstraint(
            "chosen_action IS NULL OR chosen_action IN ('wait','sms','whatsapp',"
            "'voice_bot','human_call','field_visit','legal_notice')",
            name="ck_treatment_decisions_action",
        ),
        sa.CheckConstraint(
            "chosen_channel IS NULL OR chosen_channel IN ('voice','whatsapp','sms',"
            "'email','chat','field')",
            name="ck_treatment_decisions_channel",
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('reached','no_answer','paid','ptp',"
            "'refused','undeliverable','cancelled','superseded')",
            name="ck_treatment_decisions_outcome",
        ),
    )
    op.create_index(
        "idx_treatment_decisions_tenant_id", "treatment_decisions", ["tenant_id"]
    )
    op.create_index(
        "idx_treatment_decisions_customer",
        "treatment_decisions",
        ["customer_id", "created_at"],
    )
    # The shadow scoreboard groups by mode over a window.
    op.create_index(
        "idx_treatment_decisions_mode_created",
        "treatment_decisions",
        ["mode", "created_at"],
    )
    # The executor's claim query: due, not yet enacted.
    op.execute(
        """
        CREATE INDEX idx_treatment_decisions_due
          ON treatment_decisions (scheduled_at)
          WHERE enacted IS FALSE AND chosen_action IS NOT NULL
            AND chosen_action <> 'wait'
        """
    )


def downgrade() -> None:
    op.drop_index("idx_treatment_decisions_due", table_name="treatment_decisions")
    op.drop_index(
        "idx_treatment_decisions_mode_created", table_name="treatment_decisions"
    )
    op.drop_index("idx_treatment_decisions_customer", table_name="treatment_decisions")
    op.drop_index("idx_treatment_decisions_tenant_id", table_name="treatment_decisions")
    op.drop_table("treatment_decisions")
    op.execute("DROP TRIGGER IF EXISTS trg_treatment_holds_updated_at ON treatment_holds")
    op.drop_index("uq_treatment_holds_active", table_name="treatment_holds")
    op.drop_index("idx_treatment_holds_active", table_name="treatment_holds")
    op.drop_index("idx_treatment_holds_customer_id", table_name="treatment_holds")
    op.drop_index("idx_treatment_holds_tenant_id", table_name="treatment_holds")
    op.drop_table("treatment_holds")
