"""Stop the daily rollup rounding usage away.

``usage_events`` stores ``cost_inr numeric(14,6)`` and ``units numeric(18,6)``.
``billing_usage_daily`` stored ``numeric(14,2)`` and ``numeric(14,4)``, and the
flusher's upsert adds each batch into it:

    cost_inr = billing_usage_daily.cost_inr + EXCLUDED.cost_inr

so every flush rounds to paise. Two consequences, both measured against real
data before this migration:

  * drift — 2026-07-27 ``tts_az`` rolled up to 1.69 against 1.6746 of events;
  * loss — 2026-07-26 ``llm_embed`` rolled up to **0.00** against 0.0001 of
    events. A batch smaller than half a paisa rounds to nothing and is gone.

The second is the real problem. The flusher runs every 5s by default, so a
low-rate service produces many small batches, each of which can round to zero:
the error is systematically downward, not noise that cancels. And the billing
screens read this table, not ``usage_events``, so the understatement is what
users and invoices see.

Widening to match the event columns makes the rollup exact — it is then a sum of
values at the same scale, with nothing to round. Historical rows are recomputed
from the events that produced them; rows with no events (the original seeded
demo burn) are deliberately left alone, since recomputing those would zero them.

Revision ID: 20260801_0058
Revises: 20260801_0057
Create Date: 2026-08-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0058"
down_revision: Union[str, Sequence[str], None] = "20260801_0057"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "billing_usage_daily",
        "cost_inr",
        existing_type=sa.Numeric(14, 2),
        type_=sa.Numeric(14, 6),
        existing_nullable=False,
    )
    op.alter_column(
        "billing_usage_daily",
        "units",
        existing_type=sa.Numeric(14, 4),
        type_=sa.Numeric(18, 6),
        existing_nullable=False,
    )

    # Repair the drift already stored. Scoped to (service, tenant, env, day)
    # combinations that actually have events — anything else predates metering
    # and its rollup is the only record of it.
    op.execute(
        """
        UPDATE billing_usage_daily d
           SET units    = e.units,
               cost_inr = e.cost_inr
          FROM (
                SELECT service_id, tenant_id, environment,
                       occurred_at::date AS usage_date,
                       SUM(units)    AS units,
                       SUM(cost_inr) AS cost_inr
                  FROM usage_events
                 GROUP BY service_id, tenant_id, environment, occurred_at::date
               ) e
         WHERE d.service_id  = e.service_id
           AND d.tenant_id   = e.tenant_id
           AND d.environment = e.environment
           AND d.usage_date  = e.usage_date
           AND (d.cost_inr <> e.cost_inr OR d.units <> e.units)
        """
    )


def downgrade() -> None:
    # Narrowing rounds; that is the behaviour being undone, so it is expected.
    op.alter_column(
        "billing_usage_daily",
        "units",
        existing_type=sa.Numeric(18, 6),
        type_=sa.Numeric(14, 4),
        existing_nullable=False,
    )
    op.alter_column(
        "billing_usage_daily",
        "cost_inr",
        existing_type=sa.Numeric(14, 6),
        type_=sa.Numeric(14, 2),
        existing_nullable=False,
    )
