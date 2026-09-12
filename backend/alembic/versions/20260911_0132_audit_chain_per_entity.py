"""One audit chain head per (tenant, entity) (sql/42).

Revision ID: 20260911_0132
Revises: 20260911_0131
Create Date: 2026-09-11

Mirror: sql/42_audit_chain_per_entity.sql.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260911_0132"
down_revision: Union[str, None] = "20260911_0131"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "42_audit_chain_per_entity.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
