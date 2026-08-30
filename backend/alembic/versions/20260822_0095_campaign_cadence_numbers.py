"""Campaign runs, retry cadence state and caller-ID pools (O4).

Revision ID: 20260822_0095
Revises: 20260822_0094
Create Date: 2026-08-22

Mirrors sql/22_campaigns.sql.

Three tables, each closing a gap the attempt ledger exposed rather than created.

``campaign_runs`` — a batch of missions with a window and a pace.

    The engine already answers *who* to call: ``treatment`` decides per account
    and ``enact`` dials one plan per worker iteration. What had no
    representation anywhere was the batch — "work the 30-60 bucket this
    morning" — so there was nowhere to put a pace, a window, a stop button, or
    the answer to "how far through are we". A run does not re-decide who to
    call; it groups missions that were already authorised and meters them out.

``call_cadence_state`` — one row per case, holding what the retry ladder knows.

    Retry could not exist before ``call_attempts``: a no-answer left no row, so
    there was nothing to count attempts against. The cadence is deliberately
    *not* stored on the attempt — an attempt is one dial, and the thing that
    persists across dials is the case. Keeping them apart is what stops the
    dialler inventing an escalation ladder of its own: cadence may retry the
    same action, and only the treatment engine may change the action.

``number_pools`` / ``pool_numbers`` — which caller ID a dial goes out from.

    ``twilio_ops.twilio_phone()`` reads one number from the environment for the
    whole deployment. TRAI's 1600-series mandate makes that untenable on its
    own — BFSI service and transactional calls must originate from the dedicated
    series, and promotional content is not permitted on it — and multi-tenancy
    makes it wrong twice over, since two banks cannot share a caller ID. The
    third reason is the quiet one: a number enough handsets have flagged stops
    connecting, and there was no way to observe that, let alone rotate away
    from it.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260822_0095"
down_revision: Union[str, Sequence[str], None] = "20260822_0094"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "campaign_runs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("bot_id", sa.Text(), nullable=True),
        sa.Column("deployment_id", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("cadence", sa.Text(), nullable=False, server_default="default"),
        # How the cohort was chosen. 'list' is an explicit set of customer ids;
        # 'segment' is a saved filter; 'engine' means the treatment engine
        # authorised each member individually and this run only paces them.
        sa.Column("source", sa.Text(), nullable=False, server_default="list"),
        sa.Column("selector", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        # Local-time window this run may dial in. Narrower than the statutory
        # window, never wider: contact_policy still has the final say and a run
        # cannot be configured to escape it.
        sa.Column("window_start_hour", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("window_end_hour", sa.Integer(), nullable=False, server_default="18"),
        sa.Column("max_concurrent", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("max_attempts_total", sa.Integer(), nullable=True),
        sa.Column("targets_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("targets_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_user_id", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('draft','running','paused','finished','cancelled')",
            name="ck_campaign_runs_status",
        ),
        sa.CheckConstraint("source IN ('list','segment','engine')", name="ck_campaign_runs_source"),
        sa.CheckConstraint(
            "window_start_hour >= 0 AND window_end_hour <= 24 "
            "AND window_start_hour < window_end_hour",
            name="ck_campaign_runs_window",
        ),
        sa.CheckConstraint("max_concurrent BETWEEN 1 AND 100", name="ck_campaign_runs_concurrency"),
    )
    op.create_index("idx_campaign_runs_tenant_status", "campaign_runs", ["tenant_id", "status"])

    op.create_table(
        "campaign_targets",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=True),
        sa.Column("decision_id", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_id", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["run_id"], ["campaign_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "state IN ('pending','dialing','done','failed','skipped')",
            name="ck_campaign_targets_state",
        ),
        # One row per borrower per run. A borrower appearing twice in an
        # uploaded list is a data problem, not permission to call them twice.
        sa.UniqueConstraint("run_id", "customer_id", name="ux_campaign_targets_member"),
    )
    op.execute(
        """
        CREATE INDEX idx_campaign_targets_claim ON campaign_targets (run_id, next_attempt_at)
        WHERE state = 'pending'
        """
    )

    op.create_table(
        "call_cadence_state",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        # The case this ladder belongs to. Mirrors treatment's case identity —
        # (customer, trigger kind, trigger ref) — so the two loops agree about
        # what "the same case" means instead of each having its own opinion.
        sa.Column("case_ref", sa.Text(), nullable=False, server_default=""),
        sa.Column("cadence", sa.Text(), nullable=False, server_default="default"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_id", sa.Text(), nullable=True),
        sa.Column("last_outcome", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False, server_default="open"),
        sa.Column("stopped_reason", sa.Text(), nullable=True),
        sa.Column("campaign_run_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "state IN ('open','exhausted','stopped','escalated')",
            name="ck_call_cadence_state_state",
        ),
        sa.UniqueConstraint("customer_id", "objective", "case_ref", name="ux_call_cadence_case"),
    )
    op.execute(
        """
        CREATE INDEX idx_call_cadence_due ON call_cadence_state (next_attempt_at)
        WHERE state = 'open' AND next_attempt_at IS NOT NULL
        """
    )

    op.create_table(
        "number_pools",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        # service_1600 is the TRAI series for BFSI service and transactional
        # calls. Promotional content is not permitted on it, which is why the
        # kind is a column the compiler can gate on rather than a naming
        # convention somebody has to remember.
        sa.Column("kind", sa.Text(), nullable=False, server_default="general"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "kind IN ('service_1600','promotional','general')", name="ck_number_pools_kind"
        ),
        sa.UniqueConstraint("tenant_id", "name", name="ux_number_pools_name"),
    )

    op.create_table(
        "pool_numbers",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("pool_id", sa.Text(), nullable=False),
        sa.Column("e164", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default="active"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts_7d", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("answer_rate_7d", sa.Numeric(5, 4), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["pool_id"], ["number_pools.id"], ondelete="CASCADE"),
        sa.CheckConstraint("state IN ('active','cooling','retired')", name="ck_pool_numbers_state"),
        sa.UniqueConstraint("e164", name="ux_pool_numbers_e164"),
    )
    op.execute(
        """
        CREATE INDEX idx_pool_numbers_pick ON pool_numbers (pool_id, last_used_at NULLS FIRST)
        WHERE state = 'active'
        """
    )


def downgrade() -> None:
    op.drop_table("pool_numbers")
    op.drop_table("number_pools")
    op.execute("DROP INDEX IF EXISTS idx_call_cadence_due")
    op.drop_table("call_cadence_state")
    op.execute("DROP INDEX IF EXISTS idx_campaign_targets_claim")
    op.drop_table("campaign_targets")
    op.drop_table("campaign_runs")
