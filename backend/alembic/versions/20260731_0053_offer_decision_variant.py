"""Record the A/B arm on every offer decision.

Without this, `RECO_AB_SPLIT` runs an experiment whose results cannot be
sliced: the decision rows carry the recommender that ran but not the arm the
customer was assigned to, and "control" and "challenger" become
indistinguishable the moment two arms share a scorer (a mode holdout, say).

Revision ID: 20260731_0053
Revises: 20260731_0052
Create Date: 2026-07-31
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260731_0053"
down_revision: Union[str, Sequence[str], None] = "20260731_0052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("offer_decisions", sa.Column("variant", sa.Text(), nullable=True))
    # Partial: the overwhelming majority of rows have no variant (no A/B
    # running), and indexing those buys nothing but write cost.
    op.create_index(
        "idx_offer_decisions_variant",
        "offer_decisions",
        ["variant", "created_at"],
        postgresql_where=sa.text("variant IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_offer_decisions_variant", table_name="offer_decisions")
    op.drop_column("offer_decisions", "variant")
