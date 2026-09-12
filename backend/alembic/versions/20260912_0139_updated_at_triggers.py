"""The updated_at triggers sql/13 lists, on every deployment.

Revision ID: 20260912_0139
Revises: 20260912_0138

sql/13_triggers.sql is the owner of the ``updated_at`` triggers and is
idempotent (drop-if-exists, create); a fresh build applies it, a migrated
database had only the triggers each migration remembered to add. The
migrate-from-empty parity check found ``eval_suites`` without one and the
customers trigger under its pre-rename name. Applying the file here (and
the one trigger sql/14 owns) brings every deployment to the same set.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op
from replay import apply_sql

revision: str = "20260912_0139"
down_revision: Union[str, None] = "20260912_0138"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "13_triggers.sql"


def upgrade() -> None:
    apply_sql(_SQL)
    # sql/14 owns this one (eval_suites is created there, after sql/13 runs).
    op.execute("DROP TRIGGER IF EXISTS trg_eval_suites_updated_at ON eval_suites")
    op.execute(
        "CREATE TRIGGER trg_eval_suites_updated_at BEFORE UPDATE ON eval_suites"
        " FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    # The triggers are correct on every version; nothing to undo.
    pass
