"""Allow mode='simulated' on offer_decisions.

Synthetic decision rows (scripts/simulate_offer_decisions.py) need a provenance
value of their own. Without one, the only way to keep fake traffic out of the
trainer, the replay harness and the Part 7 dashboards is for each of them to
invent its own heuristic, and the first one that forgets silently trains on
made-up data.

Revision ID: 20260731_0052
Revises: 20260731_0051
Create Date: 2026-07-31
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260731_0052"
down_revision: Union[str, Sequence[str], None] = "20260731_0051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_offer_decisions_mode", "offer_decisions", type_="check")
    op.create_check_constraint(
        "ck_offer_decisions_mode",
        "offer_decisions",
        "mode IN ('live','shadow','simulated')",
    )


def downgrade() -> None:
    # Simulated rows cannot satisfy the narrower constraint, so they have to go
    # before it is re-applied. They are synthetic by definition — there is
    # nothing here worth preserving through a rollback.
    op.execute("DELETE FROM offer_decisions WHERE mode = 'simulated'")
    op.drop_constraint("ck_offer_decisions_mode", "offer_decisions", type_="check")
    op.create_check_constraint(
        "ck_offer_decisions_mode",
        "offer_decisions",
        "mode IN ('live','shadow')",
    )
