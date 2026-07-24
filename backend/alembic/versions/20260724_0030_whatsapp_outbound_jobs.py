"""whatsapp_outbound_jobs: queue agent WhatsApp sends (SKIP LOCKED)

Revision ID: 20260724_0030
Revises: 20260723_0029
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260724_0030"
down_revision: Union[str, Sequence[str], None] = "20260723_0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_outbound_jobs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("message_id", sa.Text(), sa.ForeignKey("messages.id"), nullable=False),
        sa.Column("conversation_id", sa.Text(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("customer_id", sa.Text(), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("to_phone", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("provider_ref", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','dead')",
            name="ck_whatsapp_outbound_jobs_status",
        ),
    )
    op.create_index(
        "ix_whatsapp_outbound_jobs_status_run_after",
        "whatsapp_outbound_jobs",
        ["status", "run_after", "created_at"],
    )
    op.create_index(
        "uq_whatsapp_outbound_jobs_message_id",
        "whatsapp_outbound_jobs",
        ["message_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_whatsapp_outbound_jobs_message_id", table_name="whatsapp_outbound_jobs")
    op.drop_index("ix_whatsapp_outbound_jobs_status_run_after", table_name="whatsapp_outbound_jobs")
    op.drop_table("whatsapp_outbound_jobs")
