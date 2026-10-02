"""A thread's watermark follows its messages: a trigger, not each writer (sql/83).

Revision ID: 20261002_0179
Revises: 20261002_0178
Mirror: sql/83_message_touches_thread.sql
"""

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20261002_0179"
down_revision: Union[str, None] = "20261002_0178"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
_SQL = Path(__file__).resolve().parents[2] / "sql" / "83_message_touches_thread.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
