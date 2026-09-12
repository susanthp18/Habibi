"""W12 offer absorption: one decision log, and a suitability finding to gate it.

Revision ID: 20260910_0121
Revises: 20260910_0120
Create Date: 2026-09-10

NOT applied to the running database by this work package. Mirror:
sql/32_offer_absorption.sql.

Three kinds of object, and the lock behaviour of each is worth stating because
§15.2's W0 exit criterion is that no migration in this repo takes ACCESS
EXCLUSIVE without `NOT VALID` or `CONCURRENTLY`.

`ADD COLUMN ... NOT NULL DEFAULT 'treatment'` looks like the one thing that
rewrites a table, and on PG10 and earlier it would. On PG11+ a non-volatile
DEFAULT is stored in `pg_attribute.attmissingval` and read back for rows that
predate the column, so the ADD is a catalog write holding ACCESS EXCLUSIVE for
microseconds. `treatment_decisions` is `relkind = 'r'` -- not partitioned -- and
holds 278 rows on `collections`, so this is unmeasurable either way; it is
written this way because the same file runs on a book that is not 278 rows.

The two CHECK repairs on `chosen_action` and `chosen_channel` are the part that
would scan. Each is dropped under BOTH of its names -- `sql/05_collections.sql`
writes them inline, which auto-names them `treatment_decisions_<col>_check`,
while the migrations that touched them since named their own -- then re-added
`NOT VALID` and validated as a separate statement, so the exclusive lock covers
only the catalog write and the scan runs under SHARE UPDATE EXCLUSIVE.

`suitability_assessments` is CREATE TABLE IF NOT EXISTS and takes no lock any
running query would notice.

NO BACKFILL RUNS, and the numbers are why rather than the absence of an
opinion. Measured read-only against `collections` on 2026-09-10, the offer log
holds 16 rows: 9 live, 7 shadow, ALL on `logging_contract_version = 1`, NONE
carrying `arm_propensity`, and ZERO recording a response in the log's entire
history. Copying them across inside DDL would put rows into the treatment log
that no off-policy estimator may ever read and that carry no label -- and it
would do it in the one place a reviewer cannot see the count. They are copied
instead by `scripts/absorb_offer_decisions.py`, which prints those numbers,
defaults to `--dry-run`, and stamps the copies contract 1 so W11a's
equivalence-class filter keeps excluding them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260910_0121"
down_revision: Union[str, None] = "20260910_0120"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "32_offer_absorption.sql"


def upgrade() -> None:
    # psycopg reads a bare `%` as a placeholder even with no parameters, and
    # the mirror's comments talk about percentages. Escaped here, not in the
    # mirror: `sql/*.sql` is also fed to psql on a fresh build, where `%%`
    # would be wrong.
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
