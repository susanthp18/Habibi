"""`faq_pairs.tenant_id` and `ledger_entries.tenant_id`, defaulted from their FK.

Revision ID: 20260911_0125
Revises: 20260911_0124
Create Date: 2026-09-11

Mirror: sql/36_tenant_columns.sql. Two nullable columns, one backfill UPDATE
each (119 and 334 rows measured on `collections` on 2026-09-11, every one
resolvable through its foreign key), and a BEFORE INSERT trigger per table so
no writer changes today. Under row-level security a row left NULL is a row
nobody can read -- fail closed, and countable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260911_0125"
down_revision: Union[str, None] = "20260911_0124"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "36_tenant_columns.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
