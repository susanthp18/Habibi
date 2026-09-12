"""W8b retention: every record knows when it dies, and a citation says why.

Revision ID: 20260909_0117
Revises: 20260909_0116
Create Date: 2026-09-09

NOT applied to the running database by this work package. Mirror:
sql/28_retention.sql.

No backfill runs here, and the reason is the measurement. Read-only on
collections (2026-09-09, alembic 20260909_0115):

  treatment_decisions  304 rows, 2026-08-18 .. 2026-09-09
  contact_events       210 rows, 2026-08-19 .. 2026-09-08
  interactions          96 rows, 2026-06-22 .. 2026-09-07
  offer_decisions       16 rows, 2026-08-19 .. 2026-08-30

530 rows across the four tables, none older than eleven weeks, against a
one-year floor -- so nothing is due, nothing would be destroyed, and a backfill
inside the migration would buy an ACCESS EXCLUSIVE lock for no effect.
`agent_core.retention.backfill` stamps them, is idempotent, and runs from the
worker where it can be watched.

The ALTERs are ADD COLUMN with no default and no NOT NULL, which take a brief
lock and rewrite nothing on PG11+. The four indexes are created without
CONCURRENTLY because they are on tables this migration has just widened and
they are partial on a column every existing row holds NULL in.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260909_0117"
down_revision: Union[str, None] = "20260909_0116"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "28_retention.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
