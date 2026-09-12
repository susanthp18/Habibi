"""W7 analysis panel: one row per case, not per decision.

Revision ID: 20260909_0115
Revises: 20260908_0114
Create Date: 2026-09-09

NOT applied to the running database by this work package. Mirror:
sql/26_analysis_panel.sql.

Measured read-only on collections (2026-09-09, alembic 20260908_0114):
  treatment_decisions=302 over 21 customers; 278 cases under the current
  (customer, trigger_kind, trigger_ref) key, of which 268 are dpd_tick day-cases
  collapsing to 40 delinquency spells. No backfill runs in Alembic --
  panel.build() is idempotent and is the only writer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260909_0115"
down_revision: Union[str, None] = "20260908_0114"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "26_analysis_panel.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
