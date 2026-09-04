"""One goodwill posting per authority decision.

Revision ID: 20260905_0105
Revises: 20260904_0104
Create Date: 2026-09-05

Mirrors sql/02_customer_account.sql and sql/05_collections.sql.

``apply_goodwill`` used to SELECT the decision with no row lock, insert a
ledger waiver, then ``mark_enacted`` without inspecting rowcount. Two writers
both saw ``enacted IS FALSE`` and both returned ``ok=True`` with their own
``ledgerId``. The Mouth serialises with ``SELECT … FOR UPDATE`` now; these
indexes are the constraint the database can enforce when that lock is
missing.

* ``uq_authority_decisions_enacted_ref`` — an enacted decision names exactly
  one ledger row.
* ``uq_ledger_entries_authority_decision`` — a decision id in a waiver
  description names exactly one ledger row.

SQL is inlined so alembic does not depend on a sibling Path read at upgrade
time.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260905_0105"
down_revision: Union[str, None] = "20260904_0104"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_authority_decisions_enacted_ref
          ON authority_decisions (enacted_ref)
          WHERE enacted IS TRUE AND enacted_ref IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ledger_entries_authority_decision
          ON ledger_entries ((substring(description from 'AD-[0-9A-F]{12}')))
          WHERE type = 'waiver' AND description ~ 'AD-[0-9A-F]{12}'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_ledger_entries_authority_decision")
    op.execute("DROP INDEX IF EXISTS uq_authority_decisions_enacted_ref")
