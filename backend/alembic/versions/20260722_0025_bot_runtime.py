"""bot runtime: bot_turn_jobs, bot_tool_calls, slots, outbound key

Revision ID: 20260722_0025
Revises: 20260722_0024
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260722_0025"
down_revision: Union[str, Sequence[str], None] = "20260722_0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bot_turn_jobs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("conversation_id", sa.Text(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("interaction_id", sa.Text(), sa.ForeignKey("interactions.id"), nullable=True),
        sa.Column("customer_id", sa.Text(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("trigger_message_id", sa.Text(), sa.ForeignKey("messages.id"), nullable=True),
        sa.Column("trigger_provider_ref", sa.Text(), nullable=True),
        sa.Column("channel", sa.Text(), nullable=False, server_default="whatsapp"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("superseded_by_job_id", sa.Text(), nullable=True),
        sa.Column("outbound_message_id", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','dead','superseded','cancelled')",
            name="ck_bot_turn_jobs_status",
        ),
        sa.CheckConstraint(
            "channel IN ('whatsapp','sandbox','voice')",
            name="ck_bot_turn_jobs_channel",
        ),
    )
    op.create_index("ix_bot_turn_jobs_status_run_after", "bot_turn_jobs", ["status", "run_after", "created_at"])
    op.create_index("ix_bot_turn_jobs_conversation", "bot_turn_jobs", ["conversation_id", "status"])
    # Inbound idempotency: one job per WhatsApp wamid (Meta retries).
    op.create_index(
        "uq_bot_turn_jobs_trigger_provider_ref",
        "bot_turn_jobs",
        ["trigger_provider_ref"],
        unique=True,
        postgresql_where=sa.text("trigger_provider_ref IS NOT NULL"),
    )

    op.create_table(
        "bot_tool_calls",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("job_id", sa.Text(), sa.ForeignKey("bot_turn_jobs.id"), nullable=False),
        sa.Column("conversation_id", sa.Text(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("args", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result_ok", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result_preview", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_bot_tool_calls_job", "bot_tool_calls", ["job_id", "created_at"])
    op.create_index("ix_bot_tool_calls_conversation", "bot_tool_calls", ["conversation_id", "created_at"])

    op.add_column(
        "conversations",
        sa.Column("bot_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column("messages", sa.Column("bot_turn_job_id", sa.Text(), nullable=True))
    op.create_index(
        "uq_messages_bot_turn_job_id",
        "messages",
        ["bot_turn_job_id"],
        unique=True,
        postgresql_where=sa.text("bot_turn_job_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_messages_bot_turn_job_id", table_name="messages")
    op.drop_column("messages", "bot_turn_job_id")
    op.drop_column("conversations", "bot_state")
    op.drop_index("ix_bot_tool_calls_conversation", table_name="bot_tool_calls")
    op.drop_index("ix_bot_tool_calls_job", table_name="bot_tool_calls")
    op.drop_table("bot_tool_calls")
    op.drop_index("uq_bot_turn_jobs_trigger_provider_ref", table_name="bot_turn_jobs")
    op.drop_index("ix_bot_turn_jobs_conversation", table_name="bot_turn_jobs")
    op.drop_index("ix_bot_turn_jobs_status_run_after", table_name="bot_turn_jobs")
    op.drop_table("bot_turn_jobs")
