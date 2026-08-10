"""Make unanswered_questions writable at runtime.

The table has existed since the bot-analytics work but nothing outside
``seed_postgres`` and a demo migration ever inserted into it: the KB-gap screen,
the ``analytics_kb_gap_links`` plumbing and ``POST /kb/gaps/{id}/link`` all
shipped against hand-seeded rows. The runtime writer (``db.record_kb_gap``)
upserts on the *question text*, so it needs a uniqueness key — and there isn't
one. ``id`` is a random ``GAP-…``, so the same question asked twice an hour
apart would become two rows and ``hit_count`` would never move off 1.

The key is ``(tenant_id, lower(btrim(question)))`` rather than a stored
normalised column: it is the smallest change that makes ``ON CONFLICT`` work,
and Postgres uses the expression index as the conflict arbiter directly.

Existing rows are folded together before the index is created. The seeded set is
small and case-consistent so this is a no-op in practice, but a database seeded
twice would otherwise fail index creation — and a migration that only works on a
clean database is not a migration.

Revision ID: 20260801_0054
Revises: 20260731_0053
Create Date: 2026-08-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0054"
down_revision: Union[str, Sequence[str], None] = "20260731_0053"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Raw SQL rather than op.create_index(if_not_exists=...): two of these are
# expression indexes, which op.create_index cannot express portably, and using
# one mechanism for all three keeps upgrade and downgrade symmetric.
_NORM_INDEX = "uq_unanswered_questions_norm"
_HITS_INDEX = "idx_unanswered_questions_tenant_hits"
_SEEN_INDEX = "idx_unanswered_questions_last_seen"


def upgrade() -> None:
    conn = op.get_bind()

    # The surviving row per normalised question. min(id) is arbitrary but
    # stable, which is all that is required.
    keepers = """
        SELECT tenant_id,
               lower(btrim(question)) AS norm,
               min(id) AS keep_id
          FROM unanswered_questions
         GROUP BY tenant_id, lower(btrim(question))
        HAVING count(*) > 1
    """

    # Repoint links FIRST: analytics_kb_gap_links cascades from this table, so
    # deleting a duplicate before moving its links would silently destroy an
    # operator's resolution history.
    conn.execute(
        sa.text(
            f"""
            UPDATE analytics_kb_gap_links g
               SET unanswered_question_id = k.keep_id
              FROM ({keepers}) k
              JOIN unanswered_questions dup
                ON dup.tenant_id = k.tenant_id
               AND lower(btrim(dup.question)) = k.norm
             WHERE g.unanswered_question_id = dup.id
               AND dup.id <> k.keep_id
            """
        )
    )

    conn.execute(
        sa.text(
            f"""
            WITH k AS ({keepers}),
            rollup AS (
              SELECT k.keep_id,
                     sum(uq.hit_count) AS hits,
                     max(uq.last_seen_at) AS seen
                FROM k
                JOIN unanswered_questions uq
                  ON uq.tenant_id = k.tenant_id
                 AND lower(btrim(uq.question)) = k.norm
               GROUP BY k.keep_id
            )
            UPDATE unanswered_questions uq
               SET hit_count = rollup.hits,
                   last_seen_at = rollup.seen,
                   updated_at = now()
              FROM rollup
             WHERE uq.id = rollup.keep_id
            """
        )
    )

    conn.execute(
        sa.text(
            f"""
            DELETE FROM unanswered_questions uq
             USING ({keepers}) k
             WHERE uq.tenant_id = k.tenant_id
               AND lower(btrim(uq.question)) = k.norm
               AND uq.id <> k.keep_id
            """
        )
    )

    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {_NORM_INDEX} "
        "ON unanswered_questions (tenant_id, lower(btrim(question)))"
    )
    # Runtime capture makes this the hot read path for the KB-gap screen, which
    # sorts by hit_count and pages. Without it the sort is a full scan of a
    # table that now grows with traffic rather than with seeding.
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {_HITS_INDEX} "
        "ON unanswered_questions (tenant_id, hit_count DESC)"
    )
    # The retention sweep filters on last_seen_at.
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {_SEEN_INDEX} "
        "ON unanswered_questions (last_seen_at)"
    )


def downgrade() -> None:
    # Rows folded together in upgrade() are not restorable — that is inherent to
    # deduplication, not an oversight. Dropping the indexes returns the table to
    # its pre-migration shape, which is what downgrade can honestly offer.
    op.execute(f"DROP INDEX IF EXISTS {_SEEN_INDEX}")
    op.execute(f"DROP INDEX IF EXISTS {_HITS_INDEX}")
    op.execute(f"DROP INDEX IF EXISTS {_NORM_INDEX}")
