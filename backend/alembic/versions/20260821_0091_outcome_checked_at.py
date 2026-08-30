"""treatment_decisions.outcome_checked_at — unjam the attribution loop.

Revision ID: 20260821_0091
Revises: 20260821_0090
Create Date: 2026-08-21

Mirrors sql/05_collections.sql.

``followthrough.attribute_outcomes`` selected the oldest twenty-five
un-attributed decisions, examined each, and labelled the ones whose result was
knowable. The ones whose result was *not* knowable stayed exactly where they
were — at the front of the queue — and were re-examined on every pass.

For most rows that self-corrects: a dial goes unanswered past its grace period,
a borrower pays, a case is superseded. But an **unenacted shadow decision that
is not in a withholding arm can never be labelled at all**. Nothing was sent, so
there is nothing to call unanswered; it is not the counterfactual, so silence is
not evidence either. It can only become ``paid``, ``ptp`` or ``superseded``, and
on most accounts it becomes none of them.

Twenty-five of those accumulate and the loop stops labelling anything, forever —
silently, because the worker keeps reporting that it ran. The corpus stops
acquiring outcomes and every downstream estimate quietly freezes on the data it
already had. It bites during precisely the phase the rollout prescribes: a
shadow fortnight, where by definition nothing is enacted.

Found by a followthrough test failing after routine use of the dev API pushed
the count to exactly twenty-five.

The fix is a watermark. The loop records when it last looked at a row and orders
by that, so a row examined and found inconclusive goes to the back of the queue
instead of the front. Never-examined rows still sort first, so nothing starves.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260821_0091"
down_revision: Union[str, Sequence[str], None] = "20260821_0090"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE treatment_decisions"
        " ADD COLUMN IF NOT EXISTS outcome_checked_at timestamptz"
    )
    # Partial: only rows still awaiting an outcome are ever ordered by this, and
    # on a live book those are a small and shrinking slice of the table.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_treatment_decisions_attribution
          ON treatment_decisions (outcome_checked_at NULLS FIRST, created_at)
          WHERE outcome IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_treatment_decisions_attribution")
    op.execute("ALTER TABLE treatment_decisions DROP COLUMN IF EXISTS outcome_checked_at")
