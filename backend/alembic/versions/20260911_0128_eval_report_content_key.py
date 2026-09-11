"""`eval_reports.content_key`: what the suite was run against, as one key.

Revision ID: 20260911_0128
Revises: 20260911_0127
Create Date: 2026-09-11

Mirror: sql/38_eval_report_content_key.sql.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "20260911_0128"
down_revision: Union[str, None] = "20260911_0127"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "38_eval_report_content_key.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(_SQL.read_text(encoding="utf-8").replace("%", "%%"))


def downgrade() -> None:
    raise NotImplementedError("forward-only")
