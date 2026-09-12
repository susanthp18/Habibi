"""baseline current Postgres schema

Revision ID: 20260721_0001
Revises:
Create Date: 2026-07-21

The current enterprise schema is authored in backend/sql/*.sql and has already
been applied to collections_db. This baseline revision intentionally stamps
that known-good state so subsequent schema changes are tracked by Alembic.
"""

from typing import Sequence, Union


revision: str = "20260721_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """On an empty database, apply the schema this revision baselines.

    ``alembic/baseline/*.sql`` is ``sql/*.sql`` as the first commit shipped it,
    so ``alembic upgrade head`` from nothing walks the whole chain; on a
    database that already has the schema (every stack that existed when this
    was a no-op) nothing happens, as before."""
    from pathlib import Path

    import sqlalchemy as sa
    from alembic import op

    bind = op.get_bind()
    if sa.inspect(bind).has_table("customers"):
        return
    baseline = Path(__file__).resolve().parents[1] / "baseline"
    for path in sorted(baseline.glob("*.sql")):
        # The driver reads `%` as a placeholder; the SQL is literal (plpgsql format() uses %I).
        bind.exec_driver_sql(path.read_text(encoding="utf-8").replace("%", "%%"))


def downgrade() -> None:
    pass

