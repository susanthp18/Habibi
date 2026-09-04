"""Real keys for goodwill uniqueness on ledger_entries.

Revision ID: 20260905_0106
Revises: 20260905_0105
Create Date: 2026-09-05

Mirrors sql/02_customer_account.sql.

WP-041 put a unique index on ``substring(description, 'AD-[0-9A-F]{12}')``.
That backstop cannot cover ``post_waiver_for_dispute``: the description carries
a dispute id, not an ``AD-`` decision id, so two concurrent resolves of the
same dispute both insert. A wording change in the posting f-string would also
silently stop the regex constraining new rows.

``decision_id`` / ``dispute_id`` columns with plain unique partial indexes
replace both the regex index and the ``LIKE '%id%'`` check.

SQL is inlined so alembic does not depend on a sibling Path read at upgrade
time.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260905_0106"
down_revision: Union[str, None] = "20260905_0105"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ledger_entries ADD COLUMN IF NOT EXISTS decision_id TEXT"
    )
    op.execute(
        "ALTER TABLE ledger_entries ADD COLUMN IF NOT EXISTS dispute_id TEXT"
    )
    op.execute(
        """
        UPDATE ledger_entries le
           SET decision_id = sub.ad
          FROM (
            SELECT DISTINCT ON (substring(description from 'AD-[0-9A-F]{12}'))
                   id,
                   substring(description from 'AD-[0-9A-F]{12}') AS ad
              FROM ledger_entries
             WHERE type = 'waiver'
               AND description ~ 'AD-[0-9A-F]{12}'
             ORDER BY substring(description from 'AD-[0-9A-F]{12}'), posted_at, id
          ) sub
         WHERE le.id = sub.id
           AND le.decision_id IS NULL
        """
    )
    # No dispute backfill. Dispute ids in this system are `D-4821`, `D-SUSANTH-1`
    # — a `D-` prefix over free-form text with no fixed width and no terminator,
    # so they cannot be extracted from a description by regex the way an
    # `AD-[0-9A-F]{12}` decision id can. Measured before writing this: of 7
    # existing waiver rows, 0 contain an id of any form — the legacy wording is
    # "Goodwill fee waiver (agent: <name>)". Historical rows therefore keep
    # dispute_id NULL, which the partial unique index excludes, so nothing is
    # falsely constrained. New rows are keyed by _post at insert time.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ledger_entries_decision_id
          ON ledger_entries (decision_id)
          WHERE type = 'waiver' AND decision_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ledger_entries_dispute_id
          ON ledger_entries (dispute_id)
          WHERE type = 'waiver' AND dispute_id IS NOT NULL
        """
    )
    op.execute("DROP INDEX IF EXISTS uq_ledger_entries_authority_decision")


def downgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ledger_entries_authority_decision
          ON ledger_entries ((substring(description from 'AD-[0-9A-F]{12}')))
          WHERE type = 'waiver' AND description ~ 'AD-[0-9A-F]{12}'
        """
    )
    op.execute("DROP INDEX IF EXISTS uq_ledger_entries_dispute_id")
    op.execute("DROP INDEX IF EXISTS uq_ledger_entries_decision_id")
    op.execute("ALTER TABLE ledger_entries DROP COLUMN IF EXISTS dispute_id")
    op.execute("ALTER TABLE ledger_entries DROP COLUMN IF EXISTS decision_id")
