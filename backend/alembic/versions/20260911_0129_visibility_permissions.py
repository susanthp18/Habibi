"""Object-level reach and raw-PII access become grants (sql/39).

Revision ID: 20260911_0129
Revises: 20260911_0128
Create Date: 2026-09-11

Mirror: sql/39_visibility_permissions.sql.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260911_0129"
down_revision: Union[str, None] = "20260911_0128"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "39_visibility_permissions.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
