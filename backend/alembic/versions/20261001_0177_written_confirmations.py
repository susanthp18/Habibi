"""Written confirmations: what was sent, which call holds it, callback/dispute copies owed (sql/82).

Revision ID: 20261001_0177
Revises: 20260930_0176
Mirror: sql/82_written_confirmations.sql
"""

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20261001_0177"
down_revision: Union[str, None] = "20260930_0176"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
_SQL = Path(__file__).resolve().parents[2] / "sql" / "82_written_confirmations.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
