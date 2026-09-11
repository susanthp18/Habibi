"""One dial per key: `call_attempts.idempotency_key`.

Revision ID: 20260911_0123
Revises: 20260911_0122
Create Date: 2026-09-11

Mirror: sql/34_dial_idempotency.sql. Catalog-only -- a nullable column with no
default and a partial unique index over rows that opt in by carrying a key.
No backfill: an attempt reserved before this column existed had no key, and
NULL is the truthful value for it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "20260911_0123"
down_revision: Union[str, None] = "20260911_0122"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "34_dial_idempotency.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise NotImplementedError("forward-only")
