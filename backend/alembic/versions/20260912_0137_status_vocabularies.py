"""Status columns state their vocabulary; two fossils go (sql/47).

Revision ID: 20260912_0137
Revises: 20260912_0136
Create Date: 2026-09-12

Mirror: sql/47_status_vocabularies.sql. The base DDL (sql/02, 04, 05, 08, 10)
carries the same constraints for a fresh build.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "20260912_0137"
down_revision: Union[str, None] = "20260912_0136"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "47_status_vocabularies.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(_SQL.read_text(encoding="utf-8").replace("%", "%%"))


def downgrade() -> None:
    for table in ("accounts", "payment_plans", "invoices", "export_jobs"):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_status_check")
    op.execute("ALTER TABLE ledger_entries ADD COLUMN IF NOT EXISTS balance numeric(14,2)")
    op.execute(
        "ALTER TABLE supervisor_actions DROP CONSTRAINT IF EXISTS "
        "supervisor_actions_supervisor_user_id_fkey"
    )
    op.execute(
        "ALTER TABLE supervisor_actions ADD CONSTRAINT supervisor_actions_supervisor_user_id_fkey "
        "FOREIGN KEY (supervisor_user_id) REFERENCES users(id) ON DELETE CASCADE"
    )
