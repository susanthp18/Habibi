"""W6 PostgreSQL 16 decision substrate.

Revision ID: 20260908_0113
Revises: 20260906_0112
Create Date: 2026-09-08

NOT applied to the running database by this work package. Mirror:
sql/25_decision_substrate.sql.

Measured read-only on collections (2026-09-08, alembic 20260906_0112):
  accounts=27, treatment_decisions=302, usage_events=3314.
No shard backfill is performed in Alembic. The dry-run-first chunked utility
must be reviewed before it writes those 27 account rows.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260908_0113"
down_revision: Union[str, None] = "20260906_0112"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "25_decision_substrate.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
