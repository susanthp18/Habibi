"""Decision intelligence v2: learned rates, config proposals, buying signals (sql/75).

Revision ID: 20260927_0170
Revises: 20260927_0166 (re-point to the latest head when 0167-0169 land)
Mirror: sql/75_decision_intelligence.sql
"""

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260927_0170"
down_revision: Union[str, None] = "20260927_0166"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
_SQL = Path(__file__).resolve().parents[2] / "sql" / "75_decision_intelligence.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
