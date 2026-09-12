"""work_runtime_jobs: a lease and an attempt counter on the claim (sql/40).

Revision ID: 20260911_0130
Revises: 20260911_0129
Create Date: 2026-09-11

Mirror: sql/40_work_runtime_lease.sql.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260911_0130"
down_revision: Union[str, None] = "20260911_0129"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "40_work_runtime_lease.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
