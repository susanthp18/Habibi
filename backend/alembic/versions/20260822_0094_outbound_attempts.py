"""Outbound attempts, structured call outcomes, agent obligations (O0 + O1).

Revision ID: 20260822_0094
Revises: 20260821_0093
Create Date: 2026-08-22

Mirrors sql/21_outbound.sql.

Three tables, and the first one is the point of the release.

``call_attempts`` — one row per dial, written **before** the carrier is called.

    Until now a dial that was never answered left no trace anywhere. An
    ``interactions`` row is created by ``persist.start_voice_call``, which runs
    from ``on_client_connected`` — so a ring-out, a busy tone, a rejected call,
    a dead number and a call the contact gate refused all produced identical
    evidence: none. ``/twilio/voice/call-status`` received every one of those
    transitions and returned 204 without a write.

    The damage is not a missing dashboard. ``treatment/features.py`` computes
    ``connect_rate`` and ``responsive_hours`` from voice interactions lasting
    at least ``CONNECT_MIN_SECONDS`` — i.e. from connects only. The denominator
    was never recorded, so the single most important input to "when should we
    call this borrower" was being fitted to the numerator alone.

    Two properties are deliberate:

    * **The row precedes ``calls.create``.** A crash between the contact gate
      and the carrier previously spent a borrower's daily budget with nothing
      to show what spent it. A ``reserved`` row makes the attempt recoverable
      and an orphaned Twilio call detectable.
    * **A refused attempt is still a row.** ``suppressed_reason`` records the
      contact-policy denial against a real attempt object, which turns "our
      denial rate is 14%" from a log-grep into a query.

``call_outcomes`` — what the conversation produced, on two independent axes.

    ``interactions.disposition`` today holds one of four values derived from
    three booleans in ``capture.disposition_from_flags``, and it conflates "did
    the phone connect" with "did the conversation work". Splitting them is what
    makes ``no_answer`` retryable and ``refused`` not, and what lets reach and
    persuasion be improved by different work.

``agent_obligations`` — things *we* promised on the call.

    "I'll call you Tuesday at six" is currently spoken and forgotten. An agent
    that keeps its promises is the whole trust proposition of an automated
    collections line.

No circular FK: ``call_outcomes.attempt_id`` is unique and is the only join
between the two. A denormalised ``outcome_id`` on the attempt would be a second
pointer that can disagree with the first.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260822_0094"
down_revision: Union[str, Sequence[str], None] = "20260821_0093"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Kept in step with backend/outbound.py. A state this list does not know is a
# state the log will reject, which is the same discipline the trigger-kind
# CHECK on treatment_decisions already applies.
ATTEMPT_STATES = (
    "reserved",
    "suppressed",
    "dialing",
    "ringing",
    "answered",
    "live",
    "completed",
    "voicemail_left",
    "voicemail_skipped",
    "no_answer",
    "busy",
    "rejected",
    "failed",
    "invalid_number",
    "canceled",
    "transferred",
    "abandoned",
)

CONNECTION_OUTCOMES = (
    "no_answer",
    "busy",
    "rejected",
    "failed",
    "invalid_number",
    "voicemail",
    "wrong_party",
    "ivr_only",
    "connected",
    "suppressed",
)

BUSINESS_OUTCOMES = (
    "ptp_captured",
    "ptp_recommitted",
    "paid_in_call",
    "part_payment_agreed",
    "plan_agreed",
    "dispute_raised",
    "hardship_declared",
    "refused",
    "callback_requested",
    "wrong_number",
    "deceased",
    "opt_out_requested",
    "escalated",
    "no_resolution",
    "abandoned_by_customer",
)

# A dictionary, not a free-text field. The value is in being able to segment the
# book by it — and `forgot` is the label that tells the engine it just spent a
# voice call on somebody an SMS would have cured.
NONPAYMENT_REASONS = (
    "salary_timing",
    "income_loss",
    "medical",
    "mandate_broken",
    "disputes_amount",
    "competing_obligation",
    "forgot",
    "unwilling",
    "not_stated",
)


def _check(column: str, allowed: Sequence[str]) -> str:
    values = ",".join(f"'{v}'" for v in allowed)
    return f"{column} IN ({values})"


def upgrade() -> None:
    op.create_table(
        "call_attempts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=True),
        # Mission and campaign are plain TEXT: the mission is assembled at dial
        # time and campaign_runs is a later phase. FK'ing to a table that does
        # not exist yet would make this migration un-runnable; FK'ing later is a
        # one-line ALTER.
        sa.Column("mission_id", sa.Text(), nullable=True),
        sa.Column("campaign_run_id", sa.Text(), nullable=True),
        sa.Column("decision_id", sa.Text(), nullable=True),
        sa.Column("bot_id", sa.Text(), nullable=True),
        sa.Column("deployment_id", sa.Text(), nullable=True),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False, server_default="outreach"),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
        # The raw number stays on `customers`. Storing it again here would make
        # this table a second, unredactable copy of borrower PII whose retention
        # nobody has argued about.
        sa.Column("to_phone_hash", sa.Text(), nullable=False),
        sa.Column("to_phone_last4", sa.Text(), nullable=True),
        sa.Column("phone_slot", sa.Text(), nullable=False, server_default="primary"),
        sa.Column("from_number", sa.Text(), nullable=True),
        sa.Column("number_pool", sa.Text(), nullable=True),
        # Which rule set authorised this dial. A regulator's question is about a
        # call, not about a decision, so the stamp has to live here too.
        sa.Column("policy_version", sa.Integer(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("suppressed_reason", sa.Text(), nullable=True),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ring_sec", sa.Integer(), nullable=True),
        sa.Column("talk_sec", sa.Integer(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False, server_default="twilio"),
        sa.Column("provider_call_id", sa.Text(), nullable=True),
        sa.Column("provider_status", sa.Text(), nullable=True),
        sa.Column("provider_error", sa.Text(), nullable=True),
        sa.Column("price_inr", sa.Numeric(10, 4), nullable=True),
        sa.Column("answered_by", sa.Text(), nullable=True),
        sa.Column("right_party", sa.Boolean(), nullable=True),
        sa.Column("interaction_id", sa.Text(), nullable=True),
        # The Closer's queue marker. NULL means "this attempt still owes an
        # outcome"; a partial index on it is the whole claim query.
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("context", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decision_id"], ["treatment_decisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["interaction_id"], ["interactions.id"], ondelete="SET NULL"),
        sa.CheckConstraint(_check("state", ATTEMPT_STATES), name="ck_call_attempts_state"),
        sa.CheckConstraint(
            "answered_by IS NULL OR answered_by IN ('human','machine','ivr','fax','unknown')",
            name="ck_call_attempts_answered_by",
        ),
        sa.CheckConstraint(
            "purpose IN ('outreach','statutory','in_session')",
            name="ck_call_attempts_purpose",
        ),
        sa.CheckConstraint("attempt_no >= 1", name="ck_call_attempts_attempt_no"),
    )
    op.create_index(
        "idx_call_attempts_customer_reserved",
        "call_attempts",
        ["customer_id", sa.text("reserved_at DESC")],
    )
    op.create_index("idx_call_attempts_decision", "call_attempts", ["decision_id"])
    op.create_index(
        "idx_call_attempts_tenant_reserved",
        "call_attempts",
        ["tenant_id", sa.text("reserved_at DESC")],
    )
    # In-flight lookup for the concurrency gate. Partial so the index stays the
    # size of the live fleet rather than the size of the log.
    op.execute(
        """
        CREATE INDEX idx_call_attempts_in_flight ON call_attempts (tenant_id, reserved_at)
        WHERE state IN ('reserved','dialing','ringing','answered','live')
        """
    )
    # The Closer's claim query.
    op.execute(
        """
        CREATE INDEX idx_call_attempts_unclosed ON call_attempts (ended_at)
        WHERE closed_at IS NULL AND state <> 'reserved'
        """
    )
    # Idempotency for the status webhook. Twilio retries; two rows for one call
    # would double-count every reach metric built on this table.
    op.execute(
        """
        CREATE UNIQUE INDEX ux_call_attempts_provider_call
        ON call_attempts (provider, provider_call_id)
        WHERE provider_call_id IS NOT NULL
        """
    )

    op.create_table(
        "call_outcomes",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("attempt_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column("interaction_id", sa.Text(), nullable=True),
        sa.Column("mission_id", sa.Text(), nullable=True),
        sa.Column("decision_id", sa.Text(), nullable=True),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("connection", sa.Text(), nullable=False),
        sa.Column("business", sa.Text(), nullable=True),
        sa.Column("objective_met", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("nonpayment_reason", sa.Text(), nullable=True),
        sa.Column("commitment", postgresql.JSONB(), nullable=True),
        sa.Column("objections", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("unanswered_questions", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("sentiment_start", sa.Numeric(5, 3), nullable=True),
        sa.Column("sentiment_end", sa.Numeric(5, 3), nullable=True),
        sa.Column("escalation", sa.Text(), nullable=False, server_default="none"),
        sa.Column("compliance_flags", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("next_action_hint", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        # 'template' when the LLM was unavailable, refused, or wrote a number it
        # was not given. The column exists so a downstream reader can tell a
        # written summary from a generated one instead of trusting all of them.
        sa.Column("summary_source", sa.Text(), nullable=False, server_default="template"),
        sa.Column("summary_model", sa.Text(), nullable=True),
        sa.Column("actions_applied", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["attempt_id"], ["call_attempts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["interaction_id"], ["interactions.id"], ondelete="SET NULL"),
        sa.CheckConstraint(_check("connection", CONNECTION_OUTCOMES), name="ck_call_outcomes_connection"),
        sa.CheckConstraint(
            "business IS NULL OR " + _check("business", BUSINESS_OUTCOMES),
            name="ck_call_outcomes_business",
        ),
        sa.CheckConstraint(
            "nonpayment_reason IS NULL OR " + _check("nonpayment_reason", NONPAYMENT_REASONS),
            name="ck_call_outcomes_reason",
        ),
        sa.CheckConstraint(
            "escalation IN ('none','requested','auto','transferred')",
            name="ck_call_outcomes_escalation",
        ),
        sa.CheckConstraint(
            "summary_source IN ('template','llm')", name="ck_call_outcomes_summary_source"
        ),
        # One outcome per attempt. This is also what makes the attempt→outcome
        # join safe without a pointer column on the attempt.
        sa.UniqueConstraint("attempt_id", name="ux_call_outcomes_attempt"),
    )
    op.create_index("idx_call_outcomes_customer", "call_outcomes", ["customer_id", "created_at"])
    op.create_index("idx_call_outcomes_business", "call_outcomes", ["business"])
    op.create_index("idx_call_outcomes_reason", "call_outcomes", ["nonpayment_reason"])

    op.create_table(
        "agent_obligations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column("interaction_id", sa.Text(), nullable=True),
        sa.Column("attempt_id", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        # What the agent actually said, kept verbatim. A paraphrase is not
        # evidence, and this column is the evidence for "did we keep our word".
        sa.Column("verbatim", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False, server_default="open"),
        sa.Column("honoured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("honoured_ref", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["interaction_id"], ["interactions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["attempt_id"], ["call_attempts.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "kind IN ('callback','document','escalation','correction','waiver','written_confirm')",
            name="ck_agent_obligations_kind",
        ),
        sa.CheckConstraint(
            "state IN ('open','honoured','missed','cancelled')",
            name="ck_agent_obligations_state",
        ),
    )
    op.execute(
        """
        CREATE INDEX idx_agent_obligations_due ON agent_obligations (due_at)
        WHERE state = 'open'
        """
    )
    op.create_index("idx_agent_obligations_customer", "agent_obligations", ["customer_id"])


def downgrade() -> None:
    op.drop_table("agent_obligations")
    op.drop_table("call_outcomes")
    op.execute("DROP INDEX IF EXISTS ux_call_attempts_provider_call")
    op.execute("DROP INDEX IF EXISTS idx_call_attempts_unclosed")
    op.execute("DROP INDEX IF EXISTS idx_call_attempts_in_flight")
    op.drop_table("call_attempts")
