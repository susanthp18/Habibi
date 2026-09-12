"""PII columns are encrypted: customers -> customers_pii + the customers view (sql/48).

Revision ID: 20260912_0138
Revises: 20260912_0137
Create Date: 2026-09-12

Mirror: sql/48_pii_columns.sql, with sql/01_pii.sql (functions) before it and
sql/02_customers_view.sql (the view and its triggers) after it -- the same
three definitions a fresh build applies. Needs app.pii_key on the migration
connection (alembic/env.py passes PII_ENCRYPTION_KEY); refuses without it.

Irreversible: the plaintext columns are dropped after the backfill, and
"restore the plaintext" is not a downgrade anyone should run by accident.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260912_0138"
down_revision: Union[str, None] = "20260912_0137"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def _apply(name: str) -> None:
    apply_sql(_SQL_DIR / name, translate_pii=False)


def upgrade() -> None:
    _apply("01_pii.sql")
    _apply("48_pii_columns.sql")
    _apply("02_customers_view.sql")


def downgrade() -> None:
    raise RuntimeError("irreversible: the plaintext PII columns were dropped after encryption")
