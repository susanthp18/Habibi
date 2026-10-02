"""work_items: a bounce awaiting payment has no deadline (sql/95_views.sql).

Revision ID: 20261002_0178
Revises: 20261001_0177
Mirror: sql/95_views.sql

The bounce branch kept the 48-hour first-touch deadline after the first touch,
so a bounce waiting on the borrower counted as overdue work.
"""

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20261002_0178"
down_revision: Union[str, None] = "20261001_0177"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
_SQL = Path(__file__).resolve().parents[2] / "sql" / "95_views.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
