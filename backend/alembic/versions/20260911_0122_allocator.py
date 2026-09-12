"""W13 allocator: a capacity that can be unset, and a price that can refuse.

Revision ID: 20260911_0122
Revises: 20260910_0121
Create Date: 2026-09-11

NOT applied to the running database by this work package. Mirror:
sql/33_allocator.sql.

Lock behaviour, because §15.2's W0 exit criterion is that no migration in this
repo takes ACCESS EXCLUSIVE without `NOT VALID` or `CONCURRENTLY`:

`ALTER COLUMN capacity DROP NOT NULL` clears `pg_attribute.attnotnull`. No scan
and no rewrite -- dropping a constraint can never invalidate an existing row --
so the exclusive lock is held for the catalog write alone.

Every `ADD COLUMN` is nullable or carries a non-volatile DEFAULT, which PG11+
stores in `attmissingval` and reads back for rows that predate the column. Also
catalog-only. `capacity_duals` is `relkind = 'r'` and holds four rows on
`collections`, so this is unmeasurable either way; it is written this way
because the same file runs on a book that is not four rows.

The `capacity_source` CHECK is the one statement that would scan, so it is added
`NOT VALID` and validated separately -- the scan then runs under SHARE UPDATE
EXCLUSIVE. The partial index is created without CONCURRENTLY deliberately:
alembic runs inside a transaction, `CREATE INDEX CONCURRENTLY` cannot, and the
table is four rows. On a book where it is not, this index is the one statement
in the file worth building by hand outside the migration.

NO BACKFILL RUNS. Measured read-only against `collections` on 2026-09-11,
`capacity_duals` holds four rows from ONE solve, for `plan_date = 2026-08-22`,
solved on 2026-08-21 and never refreshed since -- and one of them reads
`capacity = 0.00, demand = 486.00, converged = t`, which is not a resource
that is 486 units oversubscribed but a resource nobody ever configured. They
are left with `capacity_source = 'unset'` and `feasible = false` because that
is what is true of them: no code that existed when they were written ever
checked whether the plan they describe fits in the capacity it claims.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260911_0122"
down_revision: Union[str, None] = "20260910_0121"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "33_allocator.sql"


def upgrade() -> None:
    # psycopg reads a bare `%` as a placeholder even with no parameters, and
    # the mirror's comments talk about percentages. Escaped here, not in the
    # mirror: `sql/*.sql` is also fed to psql on a fresh build, where `%%`
    # would be wrong.
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
