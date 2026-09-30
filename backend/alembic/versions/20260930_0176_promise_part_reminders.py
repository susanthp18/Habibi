"""A due-day reminder for every day a promise is owed (sql/81).

Revision ID: 20260930_0176
Revises: 20260929_0175
Mirror: sql/81_promise_part_reminders.sql
"""

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260930_0176"
down_revision: Union[str, None] = "20260929_0175"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
_SQL = Path(__file__).resolve().parents[2] / "sql" / "81_promise_part_reminders.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
