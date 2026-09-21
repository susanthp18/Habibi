"""Drop campaign_runs' stored counters and its unread `cadence`.

Revision ID: 20260917_0148
Revises: 20260916_0147
Create Date: 2026-09-17

Mirror: sql/57_campaign_run_derived_progress.sql.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260917_0148"
down_revision: Union[str, None] = "20260916_0147"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "57_campaign_run_derived_progress.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
