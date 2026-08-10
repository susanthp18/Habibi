"""Attribute usage events to a call and a model.

``usage_events`` records what was spent but not *what spent it*. Two dimensions
are missing and both are load-bearing:

  interaction_id  Every producer passes a hardcoded module string as
                  ``source_ref`` ("azure_speech.synthesize"), so the question
                  "what did call X cost" has no answer. The billing UI's
                  "cost per call" KPI is therefore ``total_spend /
                  resolved_calls`` — an average dressed up as a unit cost.

  model           The model name only ever reached ``meta->>'model'``, which is
                  unindexed, so spend cannot be broken down by model even though
                  a gpt-5 turn and a gpt-4o-mini turn differ by ~8x.

``source_ref`` is deliberately left alone. It is free-form provenance ("which
code path emitted this"), it is not indexed, and overloading it with an id would
conflate two different questions.

The FK is ON DELETE SET NULL, not CASCADE: a retention sweep that deletes an
interaction must not silently delete the record that money was spent. The event
degrades to unattributed spend, which still reconciles against the invoice.

``billing_usage_daily`` is untouched. Adding model to its unique key would
multiply row count by the model cardinality for a dimension the trend chart does
not use; per-model and per-call breakdowns are served from ``usage_events``
directly via the indexes below.

Revision ID: 20260801_0056
Revises: 20260801_0055
Create Date: 2026-08-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0056"
down_revision: Union[str, Sequence[str], None] = "20260801_0055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("usage_events", sa.Column("interaction_id", sa.Text(), nullable=True))
    op.add_column("usage_events", sa.Column("model", sa.Text(), nullable=True))

    op.create_foreign_key(
        "fk_usage_events_interaction",
        "usage_events",
        "interactions",
        ["interaction_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Partial: the per-call drilldown only ever reads attributed rows, and the
    # REST/batch paths that legitimately have no interaction would otherwise
    # dominate the index.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_events_interaction "
        "ON usage_events (interaction_id) WHERE interaction_id IS NOT NULL"
    )
    # Serves the per-model spend table: filter by service + window, group by model.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_events_model "
        "ON usage_events (service_id, model, occurred_at) WHERE model IS NOT NULL"
    )

    # Backfill the dimension that was already being captured, just in the wrong
    # place. Existing rows keep their spend and gain a queryable model.
    op.execute(
        """
        UPDATE usage_events
           SET model = NULLIF(meta->>'model', '')
         WHERE model IS NULL
           AND NULLIF(meta->>'model', '') IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_usage_events_model")
    op.execute("DROP INDEX IF EXISTS idx_usage_events_interaction")
    op.drop_constraint("fk_usage_events_interaction", "usage_events", type_="foreignkey")
    op.drop_column("usage_events", "model")
    op.drop_column("usage_events", "interaction_id")
