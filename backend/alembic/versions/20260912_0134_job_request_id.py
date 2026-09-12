"""request_id on the three job tables (sql/44).

Revision ID: 20260912_0134
Revises: 20260911_0133
Create Date: 2026-09-12

Mirror: sql/44_job_request_id.sql.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op
from replay import apply_sql

revision: str = "20260912_0134"
down_revision: Union[str, None] = "20260911_0133"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "44_job_request_id.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    for table in ("bot_turn_jobs", "work_runtime_jobs", "webhook_deliveries"):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS request_id")
