"""W11a promotion gate: pre-registration, and a validator who is not the author.

Revision ID: 20260910_0120
Revises: 20260909_0119
Create Date: 2026-09-10

NOT applied to the running database by this work package. Mirror:
sql/31_promotion_gate.sql.

Two objects. `treatment_pre_registrations` is CREATE TABLE IF NOT EXISTS and
takes no lock any running query would notice. The second is an ALTER on a live
table and is worth stating precisely, because §15.2's W0 exit criterion is that
no migration in this repo takes ACCESS EXCLUSIVE without `NOT VALID` or
`CONCURRENTLY`:

  ALTER TABLE treatment_model_registry
    ADD COLUMN IF NOT EXISTS pre_registration_id TEXT REFERENCES ...

A nullable ADD COLUMN with no DEFAULT is a catalog update on PG11+. It takes
ACCESS EXCLUSIVE for the duration of that catalog write and rewrites no heap,
so the lock is held for microseconds rather than for a table scan. The FOREIGN
KEY is created against a table that is empty at this instant, so its validating
scan reads zero rows. `treatment_model_registry` holds 0 rows on `collections`
and single digits anywhere else; there is nothing here for `NOT VALID` to defer.

No backfill runs, and that is the point rather than an omission. Every row
already in the registry was promoted before Gate 14 existed. Writing a
pre-registration id onto them would fabricate the exact record the gate exists
to require -- a promotion that claims to have been pre-registered and was not is
worse than one that plainly was not, because the first one passes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "20260910_0120"
down_revision: Union[str, None] = "20260909_0119"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "31_promotion_gate.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise NotImplementedError("forward-only")
