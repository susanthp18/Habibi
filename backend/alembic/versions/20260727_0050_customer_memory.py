"""Cross-call customer memory for the voice agent.

Revision ID: 20260727_0050
Revises: 20260727_0049

Nothing survived call-to-call: a caller who booked a promise-to-pay yesterday
was greeted today by an agent with no idea it existed. This table carries a
small, deliberately-constrained handover between calls.

Two halves with very different trust levels:

* ``open_commitments`` is derived from SQL (promises / disputes / callbacks /
  document requests). It is the authoritative half.
* ``summary`` is LLM-written and is forbidden from containing numbers, dates or
  any resolution verdict — see voice/memory.py for the post-filter that enforces
  that rather than trusting the prompt. It is the *colour*, never the facts.

Uses op.create_table (not op.execute) so the CI drift assertion in
.github/workflows/backend-pytest.yml can see the table and fail if
sql/04_interactions.sql is not kept in step — the mistake 20260726_0045 made
with ``voice_sessions``, which then went missing from the base schema entirely.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260727_0050"
down_revision: Union[str, Sequence[str], None] = "20260727_0049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customer_memory",
        # CASCADE: this is derived PII and must die with the customer, or the
        # hard-delete path in sql/08_redaction.sql leaves a summary behind.
        sa.Column(
            "customer_id",
            sa.Text(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        # NOT NULL DEFAULT '[]' so it can never render as the literal string
        # "null" inside a prompt.
        sa.Column(
            "open_commitments",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        # numeric, not text: CrmSink computes avg_sentiment as a float and
        # interaction_sentiment.score is already numeric(5,3). A label would
        # throw the value away and need a second mapping to get it back.
        sa.Column("last_sentiment", sa.Numeric(5, 3), nullable=True),
        # SET NULL, not CASCADE: losing one interaction must not delete the
        # customer's whole memory.
        sa.Column(
            "last_interaction_id",
            sa.Text(),
            sa.ForeignKey("interactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("last_channel", sa.Text(), nullable=True),
        sa.Column("call_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Covers the retention purge in worker.py.
    op.create_index(
        "idx_customer_memory_updated_at", "customer_memory", ["updated_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_customer_memory_updated_at", table_name="customer_memory")
    op.drop_table("customer_memory")
