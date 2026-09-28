"""Retire the old Routing / Logic builder without discarding audit evidence.

Revision ID: 20260928_0171
Revises: 20260927_0170
Mirror: sql/76_retire_legacy_routing.sql
"""

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260928_0171"
down_revision: Union[str, None] = "20260927_0170"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "76_retire_legacy_routing.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only: historical routing evidence is retained")
