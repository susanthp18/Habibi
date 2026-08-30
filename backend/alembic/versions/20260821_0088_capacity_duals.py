"""capacity_duals — the marginal value of one more agent-hour.

Revision ID: 20260821_0088
Revises: 20260821_0087
Create Date: 2026-08-21

Mirrors sql/05_collections.sql.

Per-account argmax is a local decision. The real problem is: given the whole
delinquent book, a fixed number of agent-hours, a fixed number of field slots
and a per-borrower regulatory cap, what is the best plan for tomorrow? That is a
constrained assignment, not N independent decisions.

Solving it yields shadow prices, and the shadow prices are the elegant part.
Fed back as the cost term, every *local* decision becomes globally optimal
without anybody writing a threshold down: a field visit costs its ledger price
on a quiet Tuesday and four times that when the vans are full, so the ladder
throttles itself and the rule "do not visit below Rs X of expected value" is
discovered daily instead of guessed once.

One row per resource per day. Small, append-mostly, and readable by a
collections head — the dual price on agent minutes *is* the answer to "should we
hire", stated in rupees.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260821_0088"
down_revision: Union[str, Sequence[str], None] = "20260821_0087"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS capacity_duals (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          -- The borrower's local day the plan is for, not the day it was
          -- solved. A solve that runs at 23:50 is planning tomorrow.
          plan_date date NOT NULL,
          resource TEXT NOT NULL,
          capacity numeric(14,2) NOT NULL,
          -- What the solver expects to consume at this price. Stored because
          -- "the price is high and we are still under capacity" and "the price
          -- is high and we are exactly at capacity" mean different things, and
          -- only the second one is a real scarcity signal.
          demand numeric(14,2) NOT NULL DEFAULT 0,
          -- Rupees of expected recovery forgone by giving up one unit. Zero
          -- means the resource is not binding, which is the common case and
          -- the one that must not read as "free".
          dual_price numeric(14,4) NOT NULL DEFAULT 0,
          accounts INTEGER NOT NULL DEFAULT 0,
          converged boolean NOT NULL DEFAULT false,
          iterations INTEGER NOT NULL DEFAULT 0,
          solved_at timestamptz NOT NULL DEFAULT now(),
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    # One price per resource per day. A second solve replaces the first rather
    # than accumulating, so the scorer never has to choose between two prices.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_capacity_duals_day"
        " ON capacity_duals (tenant_id, plan_date, resource)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_capacity_duals_tenant_id"
        " ON capacity_duals(tenant_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS capacity_duals")
