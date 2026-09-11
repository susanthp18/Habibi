"""audit_log is append-only for the application role (sql/43).

Revision ID: 20260911_0133
Revises: 20260911_0132
Create Date: 2026-09-11

Mirror: sql/43_audit_append_only.sql.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "20260911_0133"
down_revision: Union[str, None] = "20260911_0132"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "43_audit_append_only.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(_SQL.read_text(encoding="utf-8").replace("%", "%%"))


def downgrade() -> None:
    raise NotImplementedError("forward-only")
