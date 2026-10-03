"""Stored passages name the customer message they answer (sql/84).

Revision ID: 20261003_0180
Revises: 20261002_0179
Mirror: sql/84_suggestion_answers.sql
"""

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20261003_0180"
down_revision: Union[str, None] = "20261002_0179"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
_SQL = Path(__file__).resolve().parents[2] / "sql" / "84_suggestion_answers.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
