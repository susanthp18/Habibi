"""A handoff records what became of the transferred caller, and its wrap-up notes (sql/85).

Revision ID: 20261003_0181
Revises: 20261003_0180
Mirror: sql/85_handoff_transfer_outcome.sql
"""

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20261003_0181"
down_revision: Union[str, None] = "20261003_0180"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
_SQL = Path(__file__).resolve().parents[2] / "sql" / "85_handoff_transfer_outcome.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
